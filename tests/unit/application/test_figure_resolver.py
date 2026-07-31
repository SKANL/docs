# tests/unit/application/test_figure_resolver.py
"""Application-layer `label -> BoundFigure` resolver-builder (design.md
ADR-4/ADR-6, tasks.md S4 4.1-4.2): joins `figure-bindings.json` (agent-
authored) against `figure-catalog.json` (ingest-produced) and validates each
binding before it is allowed to reach the pure `number_and_resolve` embed
branch. File-existence I/O belongs here in `application/`, never in
`domain/`."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.figure_resolver import build_bound_figures_resolver
from docs.domain.figure_binding import BoundFigure


def _write_catalog(sections_dir: Path, figures: list[dict]) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-catalog.json").write_text(json.dumps({"figures": figures}), encoding="utf-8")


def _write_bindings(sections_dir: Path, bindings: dict[str, str]) -> None:
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-bindings.json").write_text(
        json.dumps({"schema": 1, "bindings": bindings}), encoding="utf-8"
    )


def _catalog_row(catalog_id: str, *, width_px: int | None = 300, height_px: int | None = 200) -> dict:
    return {
        "id": catalog_id,
        "sha256": "0" * 64,
        "width_px": width_px,
        "height_px": height_px,
        "origin_relative_path": f"assets/figures/{catalog_id}.png",
        "caption": "Organigrama del equipo",
        "source_role": "evidence",
        "origin_kind": "standalone",
    }


# --- absent/malformed figure-bindings.json -> empty resolver (fail-open) -------


def test_absent_bindings_file_yields_empty_resolver(tmp_path):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    assets_dir = tmp_path / "assets"

    assert build_bound_figures_resolver(sections_dir, assets_dir) == {}


def test_malformed_bindings_file_yields_empty_resolver(tmp_path):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "figure-bindings.json").write_text("{not valid json", encoding="utf-8")
    assets_dir = tmp_path / "assets"

    assert build_bound_figures_resolver(sections_dir, assets_dir) == {}


# --- binding whose file exists + non-null dims -> included ---------------------


def test_binding_with_existing_file_and_dims_is_included_as_bound_figure(tmp_path):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_catalog(sections_dir, [_catalog_row("fig-abc12345")])
    _write_bindings(sections_dir, {"organigrama": "fig-abc12345"})
    figures_dir = assets_dir / "figures"
    figures_dir.mkdir(parents=True)
    (figures_dir / "fig-abc12345.png").write_bytes(b"fake-png-bytes")

    resolver = build_bound_figures_resolver(sections_dir, assets_dir)

    assert resolver == {
        "organigrama": BoundFigure(
            label="organigrama",
            catalog_id="fig-abc12345",
            path=str(figures_dir / "fig-abc12345.png"),
            width_px=300,
            height_px=200,
            caption="Organigrama del equipo",
        )
    }


# --- binding whose file is missing -> excluded + WARN --------------------------


def test_binding_with_missing_file_is_excluded_and_warns(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_catalog(sections_dir, [_catalog_row("fig-abc12345")])
    _write_bindings(sections_dir, {"organigrama": "fig-abc12345"})
    # No file written under assets_dir/figures/ -- missing.

    resolver = build_bound_figures_resolver(sections_dir, assets_dir)

    assert resolver == {}
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "organigrama" in captured.err
    assert "fig-abc12345" in captured.err
    assert "imagen no encontrada" in captured.err


# --- binding whose catalog row has null dims -> excluded + WARN ----------------


def test_binding_with_null_dims_is_excluded_and_warns(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_catalog(sections_dir, [_catalog_row("fig-abc12345", width_px=None, height_px=None)])
    _write_bindings(sections_dir, {"organigrama": "fig-abc12345"})
    figures_dir = assets_dir / "figures"
    figures_dir.mkdir(parents=True)
    (figures_dir / "fig-abc12345.png").write_bytes(b"fake-png-bytes")

    resolver = build_bound_figures_resolver(sections_dir, assets_dir)

    assert resolver == {}
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "organigrama" in captured.err
    assert "fig-abc12345" in captured.err
    assert "sin dimensiones" in captured.err


# --- binding whose catalog id does not exist in the catalog -> excluded + WARN -


def test_binding_with_unknown_catalog_id_is_excluded_and_warns(tmp_path, capsys):
    sections_dir = tmp_path / "sections"
    assets_dir = tmp_path / "assets"
    _write_catalog(sections_dir, [])
    _write_bindings(sections_dir, {"organigrama": "fig-doesnotexist"})

    resolver = build_bound_figures_resolver(sections_dir, assets_dir)

    assert resolver == {}
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "organigrama" in captured.err
