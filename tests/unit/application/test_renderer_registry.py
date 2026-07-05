from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.cli._shared import resolve_renderer
from docs.domain.pipeline import pipeline_stage_plan
from docs.domain.ports.document_renderer_port import DocumentRendererPort


class _FakeTxtRenderer:
    """Test-only fake proving `DocumentRendererPort` is genuinely extensible
    to a second format with zero edits to `domain/pipeline.py` (document-render
    spec: `Extensibility Proof via Test Fake`). Not shipped in production."""

    output_format = "txt"

    def stage_plan(self) -> list[tuple[str, bool]]:
        return [("build-txt", True)]

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path:
        target = output or Path(config["paths"]["output_draft_dir"]) / f"{doc_id}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(config.get("body", ""), encoding="utf-8")
        return target


def _registry() -> dict[str, DocumentRendererPort]:
    return {"txt": _FakeTxtRenderer()}  # type: ignore[dict-item]


def test_fake_txt_renderer_resolves_via_the_same_registry_resolution_function():
    renderer = resolve_renderer(_registry(), "txt")
    assert renderer.output_format == "txt"


def test_fake_txt_renderer_stage_plan_flows_through_pipeline_stage_plan_unmodified():
    # No changes to domain/pipeline.py were required to support this format:
    # the resolved renderer's stage_plan() is passed straight through.
    renderer = resolve_renderer(_registry(), "txt")
    stages = pipeline_stage_plan("assemble", renderer.stage_plan())
    assert stages == [("build-txt", True)]


def test_fake_txt_renderer_stage_plan_is_distinct_from_docx_stage_plan():
    docx_stages = pipeline_stage_plan(
        "assemble",
        [("build-docx", True), ("format-audit-docx", True), ("qa-docx", True)],
    )
    txt_stages = pipeline_stage_plan("assemble", _FakeTxtRenderer().stage_plan())
    assert txt_stages != docx_stages


def test_fake_txt_renderer_build_succeeds_and_produces_output(tmp_path):
    renderer = resolve_renderer(_registry(), "txt")
    config = {"paths": {"output_draft_dir": str(tmp_path / "draft")}, "body": "hola mundo"}

    output = renderer.build("doc-1", config)

    assert output.exists()
    assert output.read_text(encoding="utf-8") == "hola mundo"


def test_unregistered_format_raises_clear_error_naming_the_format():
    import pytest

    with pytest.raises(ValueError, match="csv"):
        resolve_renderer(_registry(), "csv")
