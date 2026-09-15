# tests/unit/application/test_html_render.py
"""`HtmlRendererAdapter` — `DocumentRendererPort` implementation for HTML
output (SDD change harness-generality-and-revision, item C-html, PR2)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from docs.application.html_render import HtmlRendererAdapter
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.process.pandoc_runner_adapter import SubprocessPandocRunner


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
    return HtmlRendererAdapter(_FakeToolResolver(shutil.which("pandoc")), SubprocessPandocRunner())


# --- DocumentRendererPort contract ----------------------------------------------


def test_application_renderer_has_no_infrastructure_import():
    source = Path("src/docs/application/html_render.py").read_text(encoding="utf-8")

    assert "docs.infrastructure" not in source


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
    service = HtmlRendererAdapter(_FakeToolResolver(None), SubprocessPandocRunner())
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


def test_build_creates_the_parent_of_a_custom_output_path(tmp_path, monkeypatch):
    # Found by the first CI run. The default output dir is created, but a
    # caller-supplied `output` had its parent left to pandoc -- which pandoc
    # 3.10 tolerates and pandoc 3.1.3 does not, so this passed on a developer
    # machine and died in CI with a bare non-zero exit.
    #
    # `PdfRendererAdapter.build` already does `Path(output).parent.mkdir(...)`;
    # HTML was the inconsistent one. Asserted here without invoking pandoc:
    # the directory must exist by the time the subprocess is built.
    seen: dict[str, Path] = {}

    def fake_run(args, **kwargs):
        seen["output"] = Path(args[-1])
        Path(args[-1]).write_text("<html></html>", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pandoc")

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nCuerpo.\n", encoding="utf-8")
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }
    custom = tmp_path / "carpeta" / "que" / "no" / "existe" / "final.html"

    result = HtmlRendererAdapter(SystemToolResolverAdapter(), SubprocessPandocRunner()).build("doc-1", config, output=custom)

    assert result == custom
    assert seen["output"].parent.is_dir()


def test_build_preserves_previous_html_when_pandoc_fails(tmp_path, monkeypatch):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nCuerpo.\n", encoding="utf-8")
    output = tmp_path / "draft" / "document.html"
    output.parent.mkdir()
    output.write_text("old-build", encoding="utf-8")

    def failing_run(*args, **kwargs):
        output_argument = Path(args[0][-1])
        output_argument.write_text("partial-build", encoding="utf-8")
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("subprocess.run", failing_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pandoc")
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(output.parent)},
    }

    with pytest.raises(subprocess.CalledProcessError):
        HtmlRendererAdapter(SystemToolResolverAdapter(), SubprocessPandocRunner()).build("doc-1", config, output=output)

    assert output.read_text(encoding="utf-8") == "old-build"


def test_build_delegates_pandoc_execution_to_injected_runner(tmp_path):
    calls = []

    class FakePandocRunner:
        def run(self, args, *, check, timeout):
            calls.append((args, check, timeout))
            Path(args[-1]).write_text("<html>delegated</html>", encoding="utf-8")

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nCuerpo.\n", encoding="utf-8")
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
    }

    result = HtmlRendererAdapter(_FakeToolResolver("pandoc"), pandoc_runner=FakePandocRunner()).build("doc-1", config)

    assert result.read_text(encoding="utf-8") == "<html>delegated</html>"
    assert calls and calls[0][1:] == (True, 60)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
@pytest.mark.parametrize("variant,layout", [
    ("academic", "border-top"), ("institutional", "border-bottom"),
    ("technical", "border-left"), ("minimal", "border: none"),
    ("visual", "background"), ("custom", "text-align: right"),
])
def test_generated_cover_materializes_theme_and_variant_in_html(tmp_path, service, variant, layout):
    from html.parser import HTMLParser

    class Styles(HTMLParser):
        def __init__(self, text):
            super().__init__()
            self.active = False
            self.css = ""
            self.feed(text)

        def handle_starttag(self, tag, attrs):
            if tag == "style" and dict(attrs).get("id") == "docs-visual-theme":
                self.active = True

        def handle_endtag(self, tag):
            if tag == "style":
                self.active = False

        def handle_data(self, text):
            if self.active:
                self.css += text

    sections = tmp_path / "sections"
    sections.mkdir()
    (sections / "001-overview.md").write_text("# OVERVIEW\n\nBody text.", encoding="utf-8")
    config = {
        "title": "Theme & slots",
        "sections": [{"id": "overview", "order": 1}],
        "paths": {"sections_dir": str(sections), "output_draft_dir": str(tmp_path / "draft")},
        "format": {
            "visual_theme": {
                "colors": {"navy": "#112233", "teal": "445566", "heading_1": "#778899"},
                "typography": {"body_font": "Georgia", "body_size_pt": 11,
                               "heading_font": "Arial", "heading_1_size_pt": 22},
            },
            "cover": {"mode": "generated", "variant": variant,
                      "content": {"title": "{{title}}", "author": "Ada"},
                      "visual": {"accent": "#AA5500"},
                      "layout": {"alignment": "right", "title_size_pt": 30}},
        },
    }
    first = service.build("theme", config, output=tmp_path / "first.html")
    second = service.build("theme", config, output=tmp_path / "second.html")
    text = first.read_text(encoding="utf-8")
    css = Styles(text).css
    assert 'font-family: "Georgia"' in css and 'font-size: 11pt' in css
    assert 'font-family: "Arial"' in css and 'font-size: 22pt' in css
    assert '#112233' in css and '#778899' in css and '#AA5500' in css
    assert f'.cover--{variant}' in css and layout in css
    assert 'cover__title' in text and 'Theme &amp; slots' in text and 'cover__author' in text and 'Ada' in text
    assert first.read_bytes() == second.read_bytes()


def test_plain_html_preserves_legacy_output_without_theme(tmp_path):
    class Runner:
        def run(self, args, **kwargs):
            Path(args[-1]).write_text("<html><head></head><body>Original</body></html>", encoding="utf-8")

    (tmp_path / "001-overview.md").write_text("Body")
    config = {"sections": [{"id": "overview", "order": 1}],
              "paths": {"sections_dir": str(tmp_path), "output_draft_dir": str(tmp_path / "draft")}}
    result = HtmlRendererAdapter(_FakeToolResolver("pandoc"), Runner()).build("plain", config)
    assert result.read_text() == "<html><head></head><body>Original</body></html>"


def test_theme_css_escapes_font_values_and_normalizes_invalid_colors():
    from docs.application.html_theme import visual_theme_css

    css = visual_theme_css({"format": {"visual_theme": {
        "typography": {"body_font": '</style><script>alert("x")</script>', "body_size_pt": float("nan")},
        "colors": {"navy": "red; background:url(https://example.com)"},
    }}})
    assert "</style>" not in css and "<script>" not in css
    assert "url(" not in css and "NaN" not in css and "nan" not in css
    assert "color: #000000" in css and "font-size: 12pt" in css


def test_generated_cover_gets_layout_without_visual_theme():
    from docs.application.html_theme import visual_theme_css

    css = visual_theme_css({"cover": {"mode": "generated", "variant": "technical"}})
    assert ".cover--technical" in css and "border-left" in css
    assert "#0F766E" in css
    assert "body {" not in css  # Cover opt-in does not restyle legacy body text.
