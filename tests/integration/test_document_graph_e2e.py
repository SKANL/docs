"""ingest -> build record -> revise -> every graph query, through the sidecar API on a real workspace.

Each step is the product's own: `source ingest` and `doc revise` through the CLI, the build's
provenance record through `ProvenanceLedger` with the pipeline's own input listing (a full DOCX
build needs a passing editorial review, which this test is not about), and the answers over HTTP.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest
from typer.testing import CliRunner

from docs.api.http import Request
from docs.application.document_pipeline import _build_inputs
from docs.application.graph_queries import NAMED_QUERIES
from docs.cli.main import app as cli
from docs.composition import open_provenance_ledger
from docs.sidecar import SidecarConfig, build_application

runner = CliRunner()
DOC = "tesis"
QUERIES = (
    "claims_without_evidence", "findings_affected_by_revision", "artifacts_derived_from_input",
    "unused_references", "unmet_requirements", "stale_artifacts", "source_impact", "requirement_coverage",
)


def _cli(*args: str) -> str:
    result = runner.invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


@pytest.fixture
def workspace(canonical_cli_workspace: Path) -> Path:
    import docs.templates

    root = canonical_cli_workspace
    builtin = Path(docs.templates.__file__).parent / "builtin" / "documento-generico.json"
    (root / "templates" / "documento-generico.json").write_text(builtin.read_text(encoding="utf-8"), encoding="utf-8")
    _cli("doc", "new", DOC, "--template", "documento-generico")
    doc = root / "documents" / DOC
    # ingest: a real source file through the real command
    (doc / "inbox").mkdir(exist_ok=True)
    (doc / "inbox" / "notas.md").write_text("# Notas\n\nLa calidad se mide con encuestas.\n", encoding="utf-8")
    _cli("source", "ingest")
    _cli("collect-sources")
    sections = doc / "sections"
    (sections / "020-introduccion.md").write_text("# Introducción\n\nEl tema es la calidad (García, 2020).\n", encoding="utf-8")
    (sections / "050-referencias.md").write_text(
        "# REFERENCIAS\n\nGarcía, J. (2020). Calidad. Editorial.\nLópez, M. (2019). Otro. Editorial.\n", encoding="utf-8"
    )
    manifest = sections / "source-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    note = (doc / "inbox" / "notas.md").resolve().as_posix()
    data["sources"] = [{"path": note, "type": "approved_context", "classification": "confirmado", "sha256": "h"}]
    data["facts"] = [
        {"classification": "confirmado", "claim": "La calidad se mide con encuestas", "source": note},
        {"classification": "pendiente", "claim": "Sin respaldo", "source": "context"},
    ]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    # build: the provenance run the pipeline records (inputs = every file outside output/ and runs/)
    artifact = doc / "output" / "draft" / "tesis.docx"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"docx")
    open_provenance_ledger(doc / "runs" / "provenance.json", trusted_root=doc).record_run(
        "run-1", inputs=_build_inputs(doc), outputs=(artifact,)
    )
    # revise: edit the introduction through the semantic-edit loop (a build input changes afterwards)
    body = root / "nuevo.md"
    body.write_text("# Introducción\n\nEl tema, el objetivo y el alcance (Pérez, 2021).\n", encoding="utf-8")
    _cli("doc", "revise", "introduccion", "ampliar alcance", str(body))
    return root


def _ask(app, ws: str, query: str, **extra: str) -> dict:
    params = "&".join([f"workspace_id={ws}", f"query={query}", *(f"{k}={quote(v, safe='')}" for k, v in extra.items())])
    response = app.application.dispatch(Request("GET", f"/v2/graph?{params}"))
    assert response.status == 200, response.body
    payload = json.loads(response.body)
    assert not payload.get("graph_unavailable"), payload
    assert payload["no_data"] is False and payload["coverage"], (query, payload)
    return payload


def test_all_eight_queries_answer_from_the_files_the_pipeline_left_behind(workspace: Path) -> None:
    app = build_application(SidecarConfig(host="127.0.0.1", port=0, workspace=workspace))
    try:
        ws = app.application.workspace_registry.list()[0]["id"]
        revisions = json.loads(app.application.dispatch(Request("GET", f"/v2/revisions?workspace_id={ws}")).body)["items"]
        revision = f"{DOC}/revision/{revisions[0]['id']}"

        assert [n["label"] for n in _ask(app, ws, "claims_without_evidence")["items"]] == ["Sin respaldo"]
        unused = {n["label"] for n in _ask(app, ws, "unused_references")["items"]}
        assert unused == {"García, J. (2020). Calidad. Editorial.", "López, M. (2019). Otro. Editorial."}
        findings = _ask(app, ws, "findings_affected_by_revision", id=revision)["items"]
        assert findings and all(n["kind"] == "finding" for n in findings)

        introduction = f"{DOC}/input/sections/020-introduccion.md"
        artifact = f"{DOC}/artifact/output/draft/tesis.docx"
        assert [n["id"] for n in _ask(app, ws, "artifacts_derived_from_input", id=introduction)["items"]] == [artifact]
        assert [n["id"] for n in _ask(app, ws, "stale_artifacts")["items"]] == [artifact]  # the revision changed an input

        impact = [n["id"] for n in _ask(app, ws, "source_impact", id=introduction)["items"]]
        assert impact == [artifact, f"{DOC}/section/introduccion"]
        from_source = [n["id"] for n in _ask(app, ws, "source_impact", id=f"{DOC}/source/inbox/notas.md")["items"]]
        assert from_source == [artifact]

        unmet = _ask(app, ws, "unmet_requirements")["items"]
        assert unmet and not any("/introduccion/" in n["id"] for n in unmet)  # the revision covered them all
        rows = {r["section"]["id"]: r for r in _ask(app, ws, "requirement_coverage")["items"]}
        assert rows[f"{DOC}/section/introduccion"]["missing"] == []
        assert {n["label"] for n in rows[f"{DOC}/section/introduccion"]["satisfied"]} == {"tema", "objetivo", "alcance"}
        assert any(r["missing"] for key, r in rows.items() if key != f"{DOC}/section/introduccion")
        assert set(QUERIES) == set(NAMED_QUERIES)  # a ninth query must come with its end-to-end assertion
    finally:
        app.shutdown()
