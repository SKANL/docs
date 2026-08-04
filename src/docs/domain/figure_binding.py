# src/docs/domain/figure_binding.py
from __future__ import annotations

from dataclasses import dataclass

ASSUMED_DPI = 96
MAX_CONTENT_WIDTH_IN = 6.0  # ponytail: letter/A4 body width minus margins; config later


@dataclass(frozen=True)
class BoundFigure:
    """Application-resolved join of a `figure-bindings.json` label against
    `figure-catalog.json` (design.md ADR-4/ADR-6). `path` is the absolute,
    application-resolved file path -- pure domain code never touches the
    filesystem to build it."""

    label: str
    catalog_id: str
    path: str
    width_px: int | None
    height_px: int | None
    caption: str


def figure_width_attr(width_px: int | None) -> str:
    """Pandoc image-attribute string sizing a figure from its pixel width
    (design.md ADR-5). `None` (unknown width) yields no attribute at all;
    otherwise the width is derived at `ASSUMED_DPI` and clamped to
    `MAX_CONTENT_WIDTH_IN` so an oversized image never overflows the page."""
    if width_px is None:
        return ""
    inches = min(MAX_CONTENT_WIDTH_IN, round(width_px / ASSUMED_DPI, 2))
    return f"{{width={inches}in}}"


def figure_image_markdown(number: int, fig: BoundFigure) -> str:
    """Pandoc-embeddable markdown for a bound figure (design.md ADR-5),
    substituted for a `[[figure:label]]` marker by `number_and_resolve`
    when `label` is bound. The alt text keeps the same `Figura N.` caption
    prefix as the unbound text-only path -- embedding never changes
    numbering, only the marker's replacement."""
    caption = f"Figura {number}. {fig.caption}".rstrip()
    return f"![{caption}]({fig.path}){figure_width_attr(fig.width_px)}"


def merge_bindings(existing: dict, additions: dict) -> dict:
    """Adds `label -> id` only when `label` is ABSENT from `existing`
    (design.md Decision "pure merge + pure merge_bindings, no-clobber";
    on-demand-visual-generation) -- a generated auto-bind never overwrites a
    manual binding. Sorted-key output, deterministic. I/O stays out of this
    function."""
    merged = dict(existing)
    for label, catalog_id in additions.items():
        merged.setdefault(label, catalog_id)
    return dict(sorted(merged.items()))
