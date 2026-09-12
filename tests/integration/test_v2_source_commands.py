from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from docs.application.source_pipeline_v2 import SourcePipelineV2
from docs.cli.main import app


class _Ingest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del assets_dir
        target = Path(sections_dir) / "ingested" / "brief-md-deadbeef.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\n{\"z\": 1, \"a\": 2}\n---\nBody\n", encoding="utf-8")
        return {"processed": 1, "files": [{"status": "converted", "path": str(target)}]}


class _FailedIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del inbox_dir, sections_dir, assets_dir
        return {"status": "degraded", "processed": 0, "files": [], "errors": ["pandoc unavailable"]}


class _ExplodingIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del inbox_dir, sections_dir, assets_dir
        raise RuntimeError("source adapter crashed")


def _deps(tmp_path: Path):
    root = tmp_path / "documents" / "brief"
    context = SimpleNamespace(
        doc_id="brief",
        config={
            "paths": {
                "inbox_dir": str(root / "inbox"),
                "sections_dir": str(root / "sections"),
                "assets_dir": str(root / "assets"),
                "runs_dir": str(root / "runs"),
            },
            "structure": [{"type": "sections"}],
        },
    )
    return SimpleNamespace(
        ingest=_Ingest(),
        resolve_context=lambda doc="": context,
        workspace=SimpleNamespace(doc_root=lambda doc_id: root),
    )


def test_source_prepare_normalizes_and_compiles_atomic_outputs(tmp_path: Path) -> None:
    root = tmp_path / "document"
    config = {"structure": [{"type": "sections"}]}
    service = SourcePipelineV2(_Ingest())

    report = service.prepare("brief", root, config)

    assert report["succeeded"] is True
    normalized = next((root / "sections" / "ingested").glob("*.md"))
    assert normalized.read_text(encoding="utf-8") == (
        '---\n{\n  "a": 2,\n  "z": 1\n}\n---\nBody\n'
    )
    structure = json.loads((root / "sections" / "v2-structure.json").read_text(encoding="utf-8"))
    assert structure["parts"] == [{"type": "sections"}]
    assert (root / "runs" / "v2-prepare.json").is_file()


def test_document_ingest_is_public_and_returns_structured_report(monkeypatch, tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "ingest", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema"] == "docs.sources/v2"
    assert payload["stages"][0]["name"] == "ingest-sources"


def test_document_prepare_wires_all_source_handlers(monkeypatch, tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "prepare", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [stage["name"] for stage in payload["stages"]] == [
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
    ]


def test_source_prepare_propagates_degraded_ingest_without_claiming_success(tmp_path: Path) -> None:
    report = SourcePipelineV2(_FailedIngest()).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"][0]["succeeded"] is False
    assert report["stages"][0]["result"]["status"] == "degraded"


def test_source_ingest_converts_adapter_exception_to_failed_stage_report(tmp_path: Path) -> None:
    report = SourcePipelineV2(_ExplodingIngest()).ingest("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"][0]["result"]["status"] == "failed"
    assert report["stages"][0]["result"]["errors"] == ["source adapter crashed"]


def test_source_prepare_propagates_normalization_failure(tmp_path: Path) -> None:
    class _BrokenNormalizer:
        def _normalize(self, original: str) -> str:
            del original
            raise RuntimeError("normalizer crashed")

    report = SourcePipelineV2(_Ingest(), _BrokenNormalizer()).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"][1]["succeeded"] is False
    assert report["stages"][1]["result"]["errors"] == ["normalizer crashed"]
