# src/docs/domain/figure_filter.py
"""Mechanical role/size filter for figure candidates (design.md ADR-2;
spec: asset-management "Mechanical Role Filter for Figure Candidates").
Pure predicate, no I/O."""
from __future__ import annotations

MIN_FIGURE_DIMENSION_PX = 100  # ponytail: constant now; promote to workspace config if a doc needs a different floor


def should_catalog_figure(source_role: str, width_px: int | None, height_px: int | None) -> bool:
    if source_role in {"normative", "example"}:  # guia/reference-role -> drop
        return False
    if width_px is not None and height_px is not None and max(width_px, height_px) < MIN_FIGURE_DIMENSION_PX:
        return False  # sub-threshold junk (icons, bullets, rules)
    return True  # evidence + unknown (user-dropped), keep
