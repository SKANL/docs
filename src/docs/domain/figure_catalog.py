# src/docs/domain/figure_catalog.py
from __future__ import annotations

import re
from dataclasses import dataclass

# ponytail: simple `[[figure:fig-XXXXXXXX]]` marker, mirrors the existing
# `[[TOC]]` convention in section_rendering.py -- no new syntax family.
_FIGURE_REF_RE = re.compile(r"\[\[figure:(fig-[0-9a-f]{8})\]\]")


@dataclass(frozen=True)
class FigureEntry:
    sha256: str
    width_px: int | None
    height_px: int | None
    origin_relative_path: str
    caption: str = ""


def build(entries: list[FigureEntry]) -> dict:
    """Deterministic figure catalog (design.md Decision 6b; spec:
    asset-management "Deterministic Figure Catalog"). `id` is a stable
    hash-derived token (`fig-<sha8>`), sorted by `id` -- source subfolder is
    already carried by `origin_relative_path`, no redundant field."""
    figures: list[dict[str, str | int | None]] = [
        {
            "id": f"fig-{entry.sha256[:8]}",
            "sha256": entry.sha256,
            "width_px": entry.width_px,
            "height_px": entry.height_px,
            "origin_relative_path": entry.origin_relative_path,
            "caption": entry.caption,
        }
        for entry in entries
    ]
    figures.sort(key=lambda f: str(f["id"]))
    return {"figures": figures}


def resolve_section_figures(text: str, catalog: dict) -> list[dict | None]:
    """A section body resolves each `[[figure:fig-<id>]]` reference against
    `catalog` (spec: "A section resolves a referenced captioned figure").
    A reference to an id absent from the catalog resolves to `None` --
    never guessed, never silently dropped from the result list."""
    by_id = {figure["id"]: figure for figure in catalog.get("figures", [])}
    return [by_id.get(figure_id) for figure_id in _FIGURE_REF_RE.findall(text)]
