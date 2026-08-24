# src/docs/application/section_markdown.py
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

from docs.domain.cross_reference import number_and_resolve
from docs.domain.figure_binding import BoundFigure
from docs.domain.markdown_text import split_frontmatter


def resolve_existing_section_paths(config: dict[str, Any]) -> list[Path]:
    """Sorted, existing-on-disk section Markdown paths for `config["sections"]`
    (`NNN-<id>.md` under `paths.sections_dir`) — shared by every renderer that
    assembles from section Markdown (PR2: extracted so `HtmlRendererAdapter`
    doesn't duplicate `DocxRendererAdapter.build`'s section-resolution)."""
    sections = sorted(config["sections"], key=lambda item: item["order"])
    sections_dir = Path(config["paths"]["sections_dir"])
    return [
        sections_dir / f"{section['order']:03d}-{section['id']}.md"
        for section in sections
        if (sections_dir / f"{section['order']:03d}-{section['id']}.md").exists()
    ]


def strip_frontmatter_to_temp(
    sections: list[Path], bound_figures: dict[str, BoundFigure] | None = None
) -> list[Path]:
    """Strip YAML/JSON frontmatter from each section and number/resolve
    `[[figure:]]`/`[[table:]]`/`[[ref:]]` markers in document order (item H,
    design.md ADR-H) before any renderer hands the text to pandoc. Shared by
    every `DocumentRendererPort` implementation (PR2: extracted from
    `DocxRendererAdapter._strip_frontmatter_to_temp` so `HtmlRendererAdapter`
    reuses the exact same pass instead of duplicating it) — a pure function,
    text with no markers passes through unchanged.

    `bound_figures` (design.md ADR-4/ADR-5, S4) forwards unchanged to
    `number_and_resolve` -- a bound `[[figure:label]]` becomes pandoc-
    embeddable image markdown instead of the plain `Figura N.` text. Default
    `None` reproduces today's output byte-for-byte."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="docs_sections_"))
    bodies = [split_frontmatter(path.read_text(encoding="utf-8"))[1] for path in sections]
    numbered, warnings = number_and_resolve(
        [(path.stem, body) for path, body in zip(sections, bodies, strict=True)], bound_figures
    )
    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    stripped: list[Path] = []
    # strict=True: `numbered` is one entry per input section by contract.
    # A silent truncation here would drop a whole section from the build.
    for section_path, (_section_id, body) in zip(sections, numbered, strict=True):
        target = tmp_dir / section_path.name
        target.write_text(body, encoding="utf-8")
        stripped.append(target)
    return stripped
