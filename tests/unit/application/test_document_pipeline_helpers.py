from __future__ import annotations

import zipfile
from pathlib import Path

from docs.application.document_pipeline import (
    _available_files,
    _build_inputs,
    _capabilities_for,
    _fallback_structural_audit,
    _renderer_capabilities,
    _verify_html_artifact,
    _verify_non_docx_artifact,
    _verify_readable_artifact,
    _visual_capabilities,
)
from docs.domain.tool_capability import ToolCapability


def test_html_verifier_requires_a_single_visible_document_body(tmp_path: Path) -> None:
    valid = tmp_path / "valid.html"
    valid.write_text("<html><body><h1>Report</h1></body></html>", encoding="utf-8")
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body>   </body></html>", encoding="utf-8")
    missing_root = tmp_path / "fragment.html"
    missing_root.write_text("<body>Report</body>", encoding="utf-8")

    assert _verify_html_artifact(valid) == (True, "HTML document reopened and visual content verified")
    assert _verify_html_artifact(empty) == (False, "HTML artifact has no renderable body content")
    assert _verify_non_docx_artifact("html", missing_root) == (False, "HTML artifact is missing an html root element")
    assert _verify_non_docx_artifact("unknown", valid) == (False, "no format verifier is registered for unknown")


def test_structural_fallback_reopens_docx_and_rejects_missing_or_empty_artifacts(tmp_path: Path) -> None:
    docx = tmp_path / "report.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
    incomplete = tmp_path / "incomplete.docx"
    with zipfile.ZipFile(incomplete, "w") as archive:
        archive.writestr("word/styles.xml", "<styles/>")
    empty = tmp_path / "empty.html"
    empty.touch()

    assert _fallback_structural_audit(docx, "docx")[0] is True
    assert _fallback_structural_audit(incomplete, "docx") == (False, "structural DOCX missing word/document.xml")
    assert _fallback_structural_audit(empty, "html") == (False, f"artifact is empty: {empty}")
    assert _verify_readable_artifact(docx) == (True, "artifact is readable")
    assert _verify_readable_artifact(tmp_path / "missing.docx")[0] is False


def test_pipeline_input_and_capability_discovery_excludes_generated_outputs(tmp_path: Path) -> None:
    (tmp_path / "sections").mkdir()
    authored = tmp_path / "sections" / "overview.md"
    authored.write_text("# OVERVIEW", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    asset = tmp_path / "assets" / "figure.png"
    asset.write_bytes(b"png")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "report.docx").write_bytes(b"generated")
    (tmp_path / ".atomic-build").mkdir()
    (tmp_path / ".atomic-build" / "scratch.txt").write_text("scratch", encoding="utf-8")
    (tmp_path / "sections" / "visual-specs.json").write_text(
        '[{"type":"mermaid"},{"type":"chart"}]', encoding="utf-8"
    )

    assert _available_files(tmp_path, "assets") == (asset,)
    assert [path.relative_to(tmp_path).as_posix() for path in _build_inputs(tmp_path)] == [
        "assets/figure.png", "sections/overview.md", "sections/visual-specs.json"
    ]
    assert [item.name for item in _visual_capabilities(tmp_path)] == ["resvg", "mmdc"]

    class Renderer:
        required_capabilities = (ToolCapability("pandoc", "pandoc"),)
        optional_capabilities = ("spellcheck",)

    capabilities = _renderer_capabilities(Renderer())
    assert [(item.name, item.required) for item in capabilities] == [("pandoc", True), ("spellcheck", False)]
    registry = _capabilities_for(Renderer(), "pdf", tmp_path)
    assert {item.name for item in registry.capabilities} >= {"pandoc", "spellcheck", "pillow", "pypdfium2", "soffice", "resvg", "mmdc"}
