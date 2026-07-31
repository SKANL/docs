# src/docs/application/html_render.py
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from docs.application.figure_resolver import build_bound_figures_resolver
from docs.application.output_names import resolve_html_name
from docs.application.section_markdown import resolve_existing_section_paths, strip_frontmatter_to_temp
from docs.domain.ports.tool_resolver_port import ToolResolverPort


class HtmlRendererAdapter:
    """`DocumentRendererPort` implementation for single-file HTML output
    (design.md item C-html): pandoc markdown -> standalone, self-contained
    HTML, one call, no docx-specific assembly/audit/QA stages. Reuses the
    same section-resolution and frontmatter-strip/figure-numbering pass as
    `DocxRendererAdapter` via `application/section_markdown.py` rather than
    duplicating it."""

    output_format = "html"

    def __init__(self, tool_resolver: ToolResolverPort) -> None:
        self.tool_resolver = tool_resolver

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

        # S4 (design.md ADR-4/ADR-6): same resolver as DocxRendererAdapter --
        # a config missing `sections_dir`/`assets_dir` reproduces today's
        # behavior (empty resolver, no wiring).
        paths = config.get("paths", {})
        sections_dir = paths.get("sections_dir")
        assets_dir = paths.get("assets_dir")
        bound_figures = (
            build_bound_figures_resolver(Path(sections_dir), Path(assets_dir))
            if sections_dir and assets_dir
            else {}
        )
        stripped_sections = strip_frontmatter_to_temp(existing_sections, bound_figures)
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
        subprocess.run(
            [
                pandoc,
                *map(str, stripped_sections),
                "--standalone",
                "--embed-resources",
                "--metadata",
                f"title={self._title(doc_id, config)}",
                "-o",
                str(output),
            ],
            check=True,
        )
        return output
