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
    # the resolved renderer's stage_plan() is passed straight through (only
    # the format-agnostic "generate-visuals" stage is prepended ahead of it).
    renderer = resolve_renderer(_registry(), "txt")
    stages = pipeline_stage_plan("assemble", renderer.stage_plan())
    assert stages == [("generate-visuals", False), ("build-txt", True)]


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


# --- the registry's members must actually satisfy the port they are typed as --


def test_every_registered_renderer_matches_the_port_build_signature():
    # `Deps.renderers` is annotated `dict[str, DocumentRendererPort]`, but a
    # Protocol only constrains what a type checker sees -- and the checker
    # was never run in CI, so the registry silently held two members whose
    # `build()` returns `Path | None` against a port declaring `-> Path`.
    # HTML and PDF degrade to `None` BY DESIGN (pandoc/soffice absent), and
    # `application/pipeline.py` already branches on that `None`, so the port
    # was the side that lied. This pins the two back together.
    import inspect

    from docs.application.docx_assembly import DocxRendererAdapter
    from docs.application.html_render import HtmlRendererAdapter
    from docs.application.pdf_render import PdfRendererAdapter

    def _alternatives(annotation: str) -> set[str]:
        return {part.strip() for part in annotation.split("|")}

    # Assignability, not equality: an adapter that never degrades may narrow
    # the port's union (DOCX always returns a `Path`). What is forbidden is
    # WIDENING it — returning something the port never promised, which is
    # exactly how `Path | None` leaked past a `-> Path` declaration.
    allowed = _alternatives(inspect.signature(DocumentRendererPort.build).return_annotation)
    for adapter in (DocxRendererAdapter, HtmlRendererAdapter, PdfRendererAdapter):
        actual = _alternatives(inspect.signature(adapter.build).return_annotation)
        assert actual <= allowed, (
            f"{adapter.__name__}.build returns {sorted(actual)} but "
            f"DocumentRendererPort.build only promises {sorted(allowed)}"
        )
