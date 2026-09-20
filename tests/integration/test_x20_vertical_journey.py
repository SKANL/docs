from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from docs.api.application import X20Application
from docs.api.http import Request
from docs.application.evidence_passport import EvidencePassportService
from docs.application.generate_visuals import GenerateVisualsService
from docs.application.html_render import HtmlRendererAdapter
from docs.application.provenance import ProvenanceLedger
from docs.application.semantic_graph import SemanticGraphProjector
from docs.domain.contracts import Artifact
from docs.domain.semantic_graph import NormalizedSourceRecord
from docs.infrastructure.docx.python_docx_image_metadata_adapter import (
    PythonDocxImageMetadataAdapter,
)
from docs.infrastructure.memory.x20 import (
    InMemoryArtifactStore,
    InMemoryJobQueue,
    InMemoryRunStore,
)
from docs.infrastructure.persistence.evidence_passport_store import FileEvidencePassportStore
from docs.infrastructure.semantic_graph import SqliteSemanticGraphStore
from docs.template_compiler import compile_template


class _ToolResolver:
    def resolve_pandoc(self, _paths: dict[str, object]) -> str:
        return "deterministic-pandoc"


class _DeterministicRenderer:
    def render(self, _spec: object) -> str:
        return '<svg height="20" role="img" width="40" xmlns="http://www.w3.org/2000/svg"><title>Flow</title><rect height="20" width="40"/></svg>'


class _DeterministicRasterizer:
    def rasterize(self, _svg_path: Path, png_path: Path) -> None:
        Image.new("RGB", (40, 20), color=(10, 20, 30)).save(png_path, format="PNG")


class _DeterministicPandoc:
    def run(self, command: list[str], *, check: bool, timeout: float) -> None:
        del check, timeout
        output = Path(command[command.index("-o") + 1])
        sections = [Path(value) for value in command if value.endswith(".md")]
        body = "\n".join(section.read_text(encoding="utf-8") for section in sections)
        body = body.replace("[[figure:flow]]", '<img alt="flow" src="assets/figures/flow.svg">')
        output.write_text(f"<!doctype html><html><head><title>Vertical</title></head><body><h1>OVERVIEW</h1>{body}</body></html>", encoding="utf-8")


class _GraphStore(SqliteSemanticGraphStore):
    pass


def test_x20_vertical_journey_is_deterministic_from_template_ir_to_api_run(tmp_path: Path) -> None:
    """Exercise the full X20 path with deterministic HTML QA fallback components."""
    template = {
        "type": "vertical",
        "title": "Vertical",
        "sections": [{"id": "overview", "title": "OVERVIEW", "order": 1}],
        "section_contracts": {"overview": {}},
        "context_schema": {"topics": []},
    }
    ir = compile_template(template)
    assert len(ir.ir_hash) == 64

    sections = tmp_path / "sections"
    assets = tmp_path / "assets"
    sections.mkdir()
    (sections / "001-overview.md").write_text("# OVERVIEW\n\n[[figure:flow]]\n", encoding="utf-8")
    (sections / "visual-specs.json").write_text(
        json.dumps([{"label": "flow", "type": "flow", "source": "A->B", "caption": "Flow"}], sort_keys=True),
        encoding="utf-8",
    )
    generated = GenerateVisualsService(
        {"flow": _DeterministicRenderer()},
        _DeterministicRasterizer(),
        image_metadata=PythonDocxImageMetadataAdapter(),
    ).generate(sections, assets)
    assert generated.generated_labels == ("flow",)
    binding = json.loads((sections / "figure-bindings.json").read_text(encoding="utf-8"))
    generated_asset = next((assets / "figures").glob("*.svg"))
    catalog = json.loads((sections / "figure-catalog.json").read_text(encoding="utf-8"))

    html = HtmlRendererAdapter(_ToolResolver(), _DeterministicPandoc()).build(
        "vertical",
        {
            "title": ir.title,
            "language": "en",
            "sections": [{"id": "overview", "order": 1}],
            "paths": {
                "sections_dir": str(sections),
                "assets_dir": str(assets),
                "output_draft_dir": str(tmp_path / "output"),
            },
        },
    )
    assert html is not None
    html_text = html.read_text(encoding="utf-8")
    assert html_text.count("<html") == 1
    assert html_text.count("<body") == 1
    assert '<main id="docs-main">' in html_text
    assert generated_asset.name in html_text
    assert binding["bindings"]["flow"].startswith("fig-")
    assert any(generated_asset.stem in item["origin_relative_path"] for item in catalog["figures"])

    run_id = "run-vertical"
    ledger = ProvenanceLedger(tmp_path / "runs" / "provenance.json", trusted_root=tmp_path)
    html_digest = hashlib.sha256(html.read_bytes()).hexdigest()
    ledger.record_run(run_id, inputs=(html,), outputs=(html,))
    ledger.record_attestation(run_id, {"schema": "docs.attestation/v2", "html_sha256": html_digest})
    assert ledger.verify_attestation(run_id, {"schema": "docs.attestation/v2", "html_sha256": html_digest})

    passport_store = FileEvidencePassportStore(tmp_path / "passports")
    passport = EvidencePassportService(passport_store).finalize(
        run_id,
        ({"template_ir_hash": ir.ir_hash, "html_sha256": html_digest, "authorization": "Bearer secret"},),
    )
    assert passport.passport.entries[0]["authorization"] == "[REDACTED]"

    graph_store = _GraphStore(tmp_path / "graph.sqlite")
    projection = SemanticGraphProjector(graph_store).project(
        [NormalizedSourceRecord("document:vertical", "document", attributes={"entities": [{"id": "artifact:html", "label": "HTML"}], "edges": [{"target": "artifact:html", "relation": "renders"}]})]
    )
    assert projection.graph is not None
    assert graph_store.get() is not None

    run_store = InMemoryRunStore()
    artifact_store = InMemoryArtifactStore()
    application = X20Application(
        run_store=run_store,
        queue=InMemoryJobQueue(),
        passport_store=passport_store,
        artifact_store=artifact_store,
        graph_store=graph_store,
        documents=[{"id": "vertical"}],
    )
    artifact_store.put(Artifact("artifact:html", run_id, "html", html_digest, "text/html"))
    response = application.dispatch(
        Request(
            "POST",
            "/v1/runs",
            body={"id": run_id, "document_id": "vertical", "template_ir_hash": ir.ir_hash, "provenance_run": run_id},
        )
    )
    assert response.status == 201
    assert json.loads(response.body)["payload"]["template_ir_hash"] == ir.ir_hash
    assert application.dispatch(Request("GET", f"/v1/runs/{run_id}/passport")).status == 200
    graph_response = application.dispatch(Request("GET", "/v1/graph"))
    assert graph_response.status == 200
    assert any(node["id"] == "artifact:html" for node in json.loads(graph_response.body)["nodes"])
