# tests/unit/domain/test_figure_catalog.py
"""Figure catalog (Front F, design.md Decision 6b; spec: asset-management
"Deterministic Figure Catalog"). Pure catalog builder -- content hash,
dimensions, origin, caption. `id` is a stable hash-derived token
(`fig-<sha8>`), sorted by `id`. Dimensions `null` when unparseable, never
guessed (determinism preserved)."""
from __future__ import annotations

from docs.domain.figure_catalog import FigureEntry, build, resolve_section_figures


def test_build_produces_fig_id_from_sha256_prefix():
    entries = [FigureEntry(sha256="a" * 64, width_px=100, height_px=200, origin_relative_path="a.png")]
    catalog = build(entries)
    assert catalog["figures"][0]["id"] == "fig-" + "a" * 8


def test_build_records_required_metadata():
    entries = [
        FigureEntry(
            sha256="b" * 64,
            width_px=640,
            height_px=480,
            origin_relative_path="images/guia/page-001-image-001.png",
            caption="Figura de ejemplo",
        )
    ]
    catalog = build(entries)
    figure = catalog["figures"][0]
    assert figure["sha256"] == "b" * 64
    assert figure["width_px"] == 640
    assert figure["height_px"] == 480
    assert figure["origin_relative_path"] == "images/guia/page-001-image-001.png"
    assert figure["caption"] == "Figura de ejemplo"


def test_build_records_null_dimensions_when_unparseable_never_guessed():
    entries = [FigureEntry(sha256="c" * 64, width_px=None, height_px=None, origin_relative_path="odd.bmp")]
    figure = build(entries)["figures"][0]
    assert figure["width_px"] is None
    assert figure["height_px"] is None


def test_build_is_sorted_by_id_regardless_of_input_order():
    e1 = FigureEntry(sha256="z" * 64, width_px=1, height_px=1, origin_relative_path="z.png")
    e2 = FigureEntry(sha256="a" * 64, width_px=1, height_px=1, origin_relative_path="a.png")
    catalog = build([e1, e2])
    assert [f["id"] for f in catalog["figures"]] == ["fig-" + "a" * 8, "fig-" + "z" * 8]


def test_build_is_byte_identical_across_two_independent_builds():
    entries = [
        FigureEntry(sha256="d" * 64, width_px=10, height_px=20, origin_relative_path="d.png"),
        FigureEntry(sha256="e" * 64, width_px=None, height_px=None, origin_relative_path="e.bmp"),
    ]
    import json

    first = json.dumps(build(list(entries)), sort_keys=True)
    second = json.dumps(build(list(reversed(entries))), sort_keys=True)
    assert first == second


# --- 10.10: section resolves a referenced captioned figure --------------


def test_resolve_section_figures_finds_and_resolves_referenced_figure():
    catalog = build(
        [FigureEntry(sha256="f" * 64, width_px=100, height_px=50, origin_relative_path="f.png", caption="Diagrama")]
    )
    text = "Ver la figura a continuación. [[figure:fig-" + "f" * 8 + "]] Fin de la sección."

    resolved = resolve_section_figures(text, catalog)

    assert len(resolved) == 1
    assert resolved[0]["id"] == "fig-" + "f" * 8
    assert resolved[0]["caption"] == "Diagrama"


def test_resolve_section_figures_reports_missing_reference_as_none():
    catalog = build([])
    text = "[[figure:fig-deadbeef]]"

    resolved = resolve_section_figures(text, catalog)

    assert resolved == [None]


def test_resolve_section_figures_empty_when_no_reference():
    assert resolve_section_figures("Texto sin referencias a figuras.", build([])) == []
