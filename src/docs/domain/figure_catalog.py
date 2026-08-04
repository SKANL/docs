# src/docs/domain/figure_catalog.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FigureEntry:
    sha256: str
    width_px: int | None
    height_px: int | None
    origin_relative_path: str
    caption: str = ""
    source_role: str = ""
    origin_kind: str = ""


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
            "source_role": entry.source_role,
            "origin_kind": entry.origin_kind,
        }
        for entry in entries
    ]
    figures.sort(key=lambda f: str(f["id"]))
    return {"figures": figures}


def merge(existing_catalog: dict, generated: dict) -> dict:
    """Union of two `build()`-shaped catalogs by `id` (design.md Decision
    "pure merge + pure merge_bindings, no-clobber"; on-demand-visual-
    generation). EXISTING wins on `id` collision -- a generated (rendered)
    entry never overwrites an ingest-produced one. Re-sorted by `id`, same
    determinism as `build()`. I/O stays out of this function.

    Fails open on shape: a `figures` value that is not a list, or a row that
    is not a dict with an `id`, is skipped rather than raising -- the existing
    catalog comes from a hand-editable on-disk file, and a malformed one must
    never crash the caller (generate-visuals' WARN+skip guarantee)."""
    by_id: dict[str, dict] = {}

    def _add(catalog: dict) -> None:
        figures = catalog.get("figures", [])
        if not isinstance(figures, list):
            return
        for figure in figures:
            if isinstance(figure, dict) and "id" in figure:
                by_id[str(figure["id"])] = figure

    _add(generated)
    _add(existing_catalog)  # existing added last -> existing wins on collision

    figures = sorted(by_id.values(), key=lambda f: str(f["id"]))
    return {"figures": figures}


# ponytail: the catalog carries `width_px`/`height_px`/`caption`, but today
# the only production consumer is `status._count_figures` (which reads just
# `len(figures)`) -- those fields are written, not yet read, and `caption` is
# never even populated (both FigureEntry construction sites in ingest.py omit
# it). The spec mandates the deterministic catalog, so the fields stay; wiring
# a render-time consumer that resolves `[[figure:fig-<sha8>]]` markers back to
# these entries is the intended next step (a `resolve_section_figures` helper
# once existed here for exactly that but had zero callers, so it was removed).
