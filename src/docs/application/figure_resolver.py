# src/docs/application/figure_resolver.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from docs.domain.figure_binding import BoundFigure

_CATALOG_NAME = "figure-catalog.json"
_BINDINGS_NAME = "figure-bindings.json"


def _read_json_fail_open(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    # Fail open on shape too, not just syntax: a syntactically-valid but
    # non-object top level (e.g. a JSON array) must never reach `.get()` and
    # crash the build -- these files are hand-authored with no schema-enforcing
    # CLI (ADR-4/ADR-6: a bound label NEVER crashes the build).
    return data if isinstance(data, dict) else {}


def build_bound_figures_resolver(sections_dir: Path, assets_dir: Path) -> dict[str, BoundFigure]:
    """Application-layer join of `figure-bindings.json` (agent-authored
    `label -> catalog id`) against `figure-catalog.json` (ingest-produced
    inventory), resolving each surviving binding to an absolute image path
    under `assets_dir/figures/` (design.md ADR-4/ADR-6). File-existence I/O
    lives here in `application/` -- never in `domain/`, which stays pure.

    Absent/malformed `figure-bindings.json` fails open to an empty resolver,
    same pattern as `IngestService._read_prior_confirmed_roles`. A binding is
    admitted only if BOTH hold: the resolved file exists under
    `assets_dir/figures/`, and the catalog row has non-null
    `width_px`/`height_px` (proof the image parsed cleanly at ingest -- the
    readability signal ADR-6 reuses instead of a new port dependency here).
    Otherwise the binding is excluded and a WARN naming the label/catalog id/
    cause is printed to stderr -- a bound label never crashes the build."""
    sections_dir = Path(sections_dir)
    assets_dir = Path(assets_dir)

    bindings = _read_json_fail_open(sections_dir / _BINDINGS_NAME).get("bindings", {})
    if not isinstance(bindings, dict):
        print(
            f"WARN: 'bindings' en {_BINDINGS_NAME} no es un objeto label->id del catálogo; "
            "se omiten todas las figuras enlazadas.",
            file=sys.stderr,
        )
        return {}
    if not bindings:
        return {}

    # Only well-shaped rows (a dict with a string `id`) enter the lookup; a
    # non-list `figures` value or non-dict rows fail open (never crash).
    figures = _read_json_fail_open(sections_dir / _CATALOG_NAME).get("figures", [])
    catalog_by_id = {
        row["id"]: row
        for row in (figures if isinstance(figures, list) else [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }

    resolved: dict[str, BoundFigure] = {}
    for label, catalog_id in bindings.items():
        row = catalog_by_id.get(catalog_id)
        if row is None:
            print(
                f"WARN: [[figure:{label}]] referencia el id de catálogo '{catalog_id}', que no "
                f"existe en {_CATALOG_NAME}; se omite la imagen (no encontrada en el catálogo).",
                file=sys.stderr,
            )
            continue
        width_px = row.get("width_px")
        height_px = row.get("height_px")
        if width_px is None or height_px is None:
            print(
                f"WARN: [[figure:{label}]] ({catalog_id}) sin dimensiones registradas en el "
                "catálogo; se omite la imagen.",
                file=sys.stderr,
            )
            continue
        origin = row.get("origin_relative_path")
        if not isinstance(origin, str) or not origin:
            print(
                f"WARN: [[figure:{label}]] ({catalog_id}) sin ruta de origen en el catálogo; "
                "se omite la imagen.",
                file=sys.stderr,
            )
            continue
        path = assets_dir / "figures" / Path(origin).name
        if not path.exists():
            print(
                f"WARN: [[figure:{label}]] ({catalog_id}) imagen no encontrada en {path}; "
                "se omite la imagen.",
                file=sys.stderr,
            )
            continue
        resolved[label] = BoundFigure(
            label=label,
            catalog_id=catalog_id,
            path=str(path),
            width_px=width_px,
            height_px=height_px,
            caption=row.get("caption", ""),
        )
    return resolved
