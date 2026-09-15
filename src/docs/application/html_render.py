# src/docs/application/html_render.py
from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

from docs.application.figure_resolver import build_bound_figures_resolver
from docs.application.html_theme import visual_theme_css
from docs.application.output_names import resolve_html_name
from docs.application.section_markdown import resolve_existing_section_paths, strip_frontmatter_to_temp
from docs.domain.cover import CoverMode, render_cover_html, resolve_cover_spec
from docs.domain.figure_binding import BoundFigure
from docs.domain.ports.pandoc_runner_port import PandocRunnerPort
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.process_policy import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS


def _prefer_sibling_svg(bound_figures: dict[str, BoundFigure]) -> dict[str, BoundFigure]:
    """HTML-only sibling `.png -> .svg` swap (design.md "HTML sibling-SVG
    swap" decision, tasks.md Slice 6, on-demand-visual-generation): a
    generate-visuals entry writes `<stem>.svg` and `<stem>.png` under the
    SAME `assets_dir/figures/` stem (application/generate_visuals.py). When
    a bound figure's resolved `.path` is such a `.png` and its same-stem
    `.svg` sibling exists on disk, HTML embeds the crisp vector instead --
    every other field (dims, caption, label) stays unchanged so the emitted
    `{width=Xin}` pandoc attribute is identical. A plain ingested photo (no
    sibling `.svg`) or a non-`.png` path passes through unchanged.
    `docx_assembly.py` never calls this -- docx always embeds the PNG
    (pandoc#9195 blocker on SVG-in-docx)."""
    swapped: dict[str, BoundFigure] = {}
    for label, fig in bound_figures.items():
        path = Path(fig.path)
        sibling = path.with_suffix(".svg")
        swapped[label] = replace(fig, path=str(sibling)) if path.suffix == ".png" and sibling.exists() else fig
    return swapped


def _ensure_accessible_document(html: str, language: str) -> str:
    """Add semantic landmarks that Pandoc does not guarantee."""
    def add_language(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\blang\s*=", tag, flags=re.IGNORECASE):
            return tag
        return tag[:-1] + f' lang="{language}">'

    html = re.sub(r"<html\b[^>]*>", add_language, html, count=1, flags=re.IGNORECASE)
    if not re.search(r"<main\b", html, flags=re.IGNORECASE):
        html, opened = re.subn(
            r"(<body\b[^>]*>)",
            r'\1<main id="docs-main">',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
        if opened:
            html = re.sub(r"</body\s*>", "</main></body>", html, count=1, flags=re.IGNORECASE)
    return html


class HtmlRendererAdapter:
    """`DocumentRendererPort` implementation for single-file HTML output
    (design.md item C-html): pandoc markdown -> standalone, self-contained
    HTML, one call, no docx-specific assembly/audit/QA stages. Reuses the
    same section-resolution and frontmatter-strip/figure-numbering pass as
    `DocxRendererAdapter` via `application/section_markdown.py` rather than
    duplicating it."""

    output_format = "html"

    def __init__(self, tool_resolver: ToolResolverPort, pandoc_runner: PandocRunnerPort) -> None:
        self.tool_resolver = tool_resolver
        self.pandoc_runner = pandoc_runner

    def stage_plan(self) -> list[tuple[str, bool]]:
        return [("build-html", True)]

    def _html_name(self, doc_id: str, config: dict[str, Any]) -> str:
        return resolve_html_name(doc_id, config)

    def _title(self, doc_id: str, config: dict[str, Any]) -> str:
        # The document's declared template title if present, else the doc id
        # -- never the first section's filename stem, which is what pandoc
        # falls back to for <title> when no metadata title is passed.
        return str(config.get("title") or doc_id)

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path | None:
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
        if not pandoc:
            # Unlike DocxRendererAdapter (docx is the primary, always-required
            # format), HTML degrades cleanly when pandoc is absent: WARN and
            # skip rather than fail the whole pipeline run for a secondary,
            # opt-in output format.
            print(
                "WARN: Pandoc no está disponible en PATH. Se omite la salida HTML.",
                file=sys.stderr,
            )
            return None

        existing_sections = resolve_existing_section_paths(config)
        if not existing_sections:
            raise RuntimeError("No hay secciones Markdown para ensamblar. Ejecuta `build-section resumen` primero.")

        output_dir = Path(config["paths"]["output_draft_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output or output_dir / self._html_name(doc_id, config)
        # A caller-supplied `output` may point anywhere, and its parent is
        # ours to create -- not pandoc's. pandoc 3.10 tolerates a missing
        # parent and 3.1.3 exits 1, so leaving it to the toolchain passed on a
        # developer machine and failed in CI. `PdfRendererAdapter.build`
        # already does this; HTML was the inconsistent one.
        Path(output).parent.mkdir(parents=True, exist_ok=True)

        # S4 (design.md ADR-4/ADR-6): same resolver as DocxRendererAdapter --
        # a config missing `sections_dir`/`assets_dir` reproduces today's
        # behavior (empty resolver, no wiring).
        paths = config.get("paths", {})
        sections_dir = paths.get("sections_dir")
        assets_dir = paths.get("assets_dir")
        bound_figures = (
            _prefer_sibling_svg(build_bound_figures_resolver(Path(sections_dir), Path(assets_dir)))
            if sections_dir and assets_dir
            else {}
        )
        generated_cover = resolve_cover_spec(config)
        temp_cover = (
            tempfile.TemporaryDirectory(prefix="docs_cover_")
            if generated_cover and generated_cover.mode is CoverMode.GENERATED
            else nullcontext()
        )
        with temp_cover as temp_dir:
            stripped_sections = strip_frontmatter_to_temp(existing_sections, bound_figures)
            if generated_cover and generated_cover.mode is CoverMode.GENERATED:
                assert temp_dir is not None
                cover_path = Path(temp_dir) / "000-cover.html"
                cover_path.write_text(render_cover_html(generated_cover, config), encoding="utf-8")
                stripped_sections.insert(0, cover_path)
        # `--standalone` produces a full HTML document (not a fragment);
        # `--embed-resources` inlines any referenced assets so the artifact
        # stays a single self-contained file (design.md Open Question:
        # single-file, default). No `--metadata date=...`/wall-clock input is
        # ever passed, so pandoc has nothing non-deterministic to stamp into
        # the output (unlike docx's zip container, plain HTML has no
        # container-level timestamp to normalize). `--metadata title=` is
        # passed explicitly -- without it pandoc's standalone HTML falls back
        # to the first input filename (a section stem like "010-overview")
        # for <title>, which is not the document's title.
            fd, temporary_output = tempfile.mkstemp(
                prefix=f".{Path(output).stem}.", suffix=Path(output).suffix or ".html", dir=Path(output).parent
            )
            os.close(fd)
            temporary_path = Path(temporary_output)
            try:
                self.pandoc_runner.run(
                    [
                        pandoc,
                        "--from",
                        "markdown",
                        *map(str, stripped_sections),
                        "--standalone",
                        "--embed-resources",
                        "--metadata",
                        f"title={self._title(doc_id, config)}",
                        "-o",
                        str(temporary_path),
                    ],
                    check=True,
                    timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
                )
                if not temporary_path.exists() or temporary_path.stat().st_size == 0:
                    raise RuntimeError("Pandoc produjo un HTML vacío o inexistente")
                css = visual_theme_css(config)
                text = temporary_path.read_text(encoding="utf-8")
                project = config.get("project")
                project_language = project.get("language") if isinstance(project, dict) else None
                language = str(config.get("language") or config.get("lang") or project_language or "en")
                text = _ensure_accessible_document(text, language)
                if css:
                    style = f'<style id="docs-visual-theme">\n{css}\n</style>\n'
                    text, count = re.subn(r"</head\s*>", lambda _: style + "</head>", text, count=1, flags=re.IGNORECASE)
                    if not count:
                        raise RuntimeError("Cannot apply HTML theme: generated document has no head element")
                temporary_path.write_text(text, encoding="utf-8", newline="\n")
                os.replace(temporary_path, output)
            finally:
                temporary_path.unlink(missing_ok=True)
        return output
