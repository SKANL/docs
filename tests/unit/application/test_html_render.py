# tests/unit/application/test_html_render.py
"""`HtmlRendererAdapter` — `DocumentRendererPort` implementation for HTML
output (SDD change harness-generality-and-revision, item C-html, PR2)."""
from __future__ import annotations

import shutil

import pytest

from docs.application.html_render import HtmlRendererAdapter
from docs.domain.ports.document_renderer_port import DocumentRendererPort


class _FakeToolResolver:
    def __init__(self, pandoc: str | None) -> None:
        self._pandoc = pandoc

    def resolve_pandoc(self, paths):
        return self._pandoc

    def resolve_libreoffice(self, paths):
        return None

    def resolve_java(self, paths):
        return None


@pytest.fixture
def service() -> HtmlRendererAdapter:
    return HtmlRendererAdapter(_FakeToolResolver(shutil.which("pandoc")))


# --- DocumentRendererPort contract ----------------------------------------------


def test_html_renderer_adapter_declares_html_output_format(service):
    assert service.output_format == "html"


def test_html_renderer_adapter_satisfies_document_renderer_port(service: DocumentRendererPort):
    assert service.output_format == "html"
    assert service.stage_plan() == [("build-html", True)]


def test_html_renderer_adapter_resolves_via_registry_by_format(service):
    from docs.cli._shared import resolve_renderer

    registry = {"html": service}
    resolved = resolve_renderer(registry, "html")
    assert resolved is service


# --- build: pandoc absent -> WARN + skip (never crash) --------------------------


def test_build_returns_none_and_warns_when_pandoc_unavailable(tmp_path, capsys):
    service = HtmlRendererAdapter(_FakeToolResolver(None))
    config = {"sections": [], "paths": {"sections_dir": str(tmp_path), "output_draft_dir": str(tmp_path)}}

    result = service.build("doc-1", config)

    assert result is None
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "Pandoc" in captured.err


# --- build: no markdown sections -----------------------------------------------


def test_build_raises_when_no_markdown_sections_exist(tmp_path, service):
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(tmp_path / "sections"), "output_draft_dir": str(tmp_path / "draft")},
    }
    (tmp_path / "sections").mkdir()
    with pytest.raises(RuntimeError, match="No hay secciones"):
        service.build("doc-1", config)


# --- build: output naming --------------------------------------------------------


def test_html_name_defaults_to_doc_id_derived_name(service):
    assert service._html_name("doc-1", {}) == "doc-1-draft.html"


def test_html_name_uses_configured_html_name_when_present(service):
    config = {"output": {"html_name": "custom.html"}}
    assert service._html_name("doc-1", config) == "custom.html"


# --- build: real pandoc invocation -----------------------------------------------


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_produces_html_at_default_output_path(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nContenido del resumen.\n", encoding="utf-8")

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(draft_dir)},
    }

    output = service.build("doc-1", config)

    assert output == draft_dir / "doc-1-draft.html"
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "Contenido del resumen" in text
    assert "<!DOCTYPE html>" in text


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_sets_html_title_to_configured_document_title(tmp_path, service):
    # Regression: the <title> used to end up as the first section's filename
    # stem (e.g. "010-overview") because pandoc falls back to the first input
    # filename when no title metadata is given. It must reflect the document.
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-overview.md").write_text("Contenido.\n", encoding="utf-8")

    config = {
        "title": "Technical Report (SRS)",
        "sections": [{"id": "overview", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }

    output = service.build("doc-1", config)
    text = output.read_text(encoding="utf-8")

    assert "<title>Technical Report (SRS)</title>" in text
    assert "001-overview" not in text


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_falls_back_to_doc_id_for_title_when_config_has_no_title(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-overview.md").write_text("Contenido.\n", encoding="utf-8")

    config = {
        "sections": [{"id": "overview", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }

    output = service.build("doc-1", config)
    text = output.read_text(encoding="utf-8")

    assert "<title>doc-1</title>" in text


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_uses_configured_html_name_and_custom_output_path(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nTexto.\n", encoding="utf-8")
    custom_output = tmp_path / "custom" / "final.html"

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }

    output = service.build("doc-1", config, output=custom_output)

    assert output == custom_output
    assert output.exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_numbers_figures_and_resolves_refs_across_sections(tmp_path, service):
    # Proves HtmlRendererAdapter reuses the SAME frontmatter-strip/numbering
    # pass as DocxRendererAdapter (design.md item C-html) rather than
    # duplicating it.
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text(
        "# Resumen\n\n[[figure:organigrama]] Organigrama del equipo.\n", encoding="utf-8"
    )
    (sections_dir / "002-anexos.md").write_text(
        "# Anexos\n\nConsulte [[ref:organigrama]] para más detalle.\n", encoding="utf-8"
    )

    config = {
        "sections": [{"id": "resumen", "order": 1}, {"id": "anexos", "order": 2}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(draft_dir)},
    }

    output = service.build("doc-1", config)
    text = output.read_text(encoding="utf-8")
    assert "Figura 1. Organigrama del equipo." in text
    assert "Consulte Ver Figura 1 para más detalle." in text
