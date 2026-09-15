# tests/unit/domain/test_figure_catalog.py
"""Figure catalog (Front F, design.md Decision 6b; spec: asset-management
"Deterministic Figure Catalog"). Pure catalog builder -- content hash,
dimensions, origin, caption. `id` is a stable hash-derived token
(`fig-<sha8>`), sorted by `id`. Dimensions `null` when unparseable, never
guessed (determinism preserved)."""
from __future__ import annotations

from docs.domain.figure_catalog import FigureEntry, build, merge


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


def test_figure_entry_source_role_and_origin_kind_default_empty():
    entry = FigureEntry(sha256="f" * 64, width_px=1, height_px=1, origin_relative_path="f.png")
    assert entry.source_role == ""
    assert entry.origin_kind == ""


def test_build_round_trips_source_role_and_origin_kind():
    entries = [
        FigureEntry(
            sha256="g" * 64,
            width_px=640,
            height_px=480,
            origin_relative_path="images/evidence/page-001-image-001.png",
            caption="Figura evidencia",
            source_role="evidence",
            origin_kind="standalone",
        )
    ]
    figure = build(entries)["figures"][0]
    assert figure["source_role"] == "evidence"
    assert figure["origin_kind"] == "standalone"


def test_build_with_new_fields_is_byte_identical_across_two_independent_builds():
    entries = [
        FigureEntry(
            sha256="h" * 64,
            width_px=10,
            height_px=20,
            origin_relative_path="h.png",
            source_role="evidence",
            origin_kind="standalone",
        ),
        FigureEntry(
            sha256="i" * 64,
            width_px=None,
            height_px=None,
            origin_relative_path="i.bmp",
            source_role="unknown",
            origin_kind="pdf_render",
        ),
    ]
    import json

    first = json.dumps(build(list(entries)), sort_keys=True)
    second = json.dumps(build(list(reversed(entries))), sort_keys=True)
    assert first == second


# --- merge() -- on-demand-visual-generation, design.md "pure merge + pure
# merge_bindings, no-clobber": union by `id`, EXISTING wins on collision
# (generated never overwrites an ingest-produced entry), re-sorted by `id`.


def test_merge_preserves_all_entries_no_clobber():
    existing = build(
        [
            FigureEntry(
                sha256="a" * 64,
                width_px=1,
                height_px=1,
                origin_relative_path="a.png",
                origin_kind="standalone",
            )
        ]
    )
    generated = build(
        [
            FigureEntry(
                sha256="a" * 64,
                width_px=999,
                height_px=999,
                origin_relative_path="generated-a.png",
                origin_kind="generated",
            ),
            FigureEntry(
                sha256="b" * 64,
                width_px=2,
                height_px=2,
                origin_relative_path="b.png",
                origin_kind="generated",
            ),
        ]
    )

    merged = merge(existing, generated)

    fig_a = next(f for f in merged["figures"] if f["id"] == "fig-" + "a" * 8)
    assert fig_a["origin_relative_path"] == "a.png"
    assert fig_a["origin_kind"] == "standalone"
    fig_b = next(f for f in merged["figures"] if f["id"] == "fig-" + "b" * 8)
    assert fig_b["origin_kind"] == "generated"
    assert len(merged["figures"]) == 2


def test_merge_is_resorted_and_deterministic():
    existing = build(
        [FigureEntry(sha256="m" * 64, width_px=1, height_px=1, origin_relative_path="m.png")]
    )
    gen_entries = [
        FigureEntry(sha256="z" * 64, width_px=1, height_px=1, origin_relative_path="z.png"),
        FigureEntry(sha256="a" * 64, width_px=1, height_px=1, origin_relative_path="a.png"),
    ]
    import json as _json

    first = _json.dumps(merge(existing, build(gen_entries)), sort_keys=True)
    second = _json.dumps(merge(existing, build(list(reversed(gen_entries)))), sort_keys=True)
    assert first == second

    ids = [f["id"] for f in merge(existing, build(gen_entries))["figures"]]
    assert ids == sorted(ids)


def test_merge_fails_open_on_malformed_existing_catalog():
    # The existing catalog comes from a hand-editable on-disk file; a malformed
    # one (figures not a list, or non-dict / id-less rows) must be skipped, not
    # raise -- upholding generate-visuals' WARN+skip guarantee (review WARNING).
    generated = build(
        [FigureEntry(sha256="a" * 64, width_px=1, height_px=1, origin_relative_path="a.png", origin_kind="generated")]
    )
    gen_id = "fig-" + "a" * 8

    # figures value is not a list
    merged = merge({"figures": None}, generated)
    assert [f["id"] for f in merged["figures"]] == [gen_id]

    # junk rows (non-dict, id-less) are skipped; the valid generated row survives
    merged = merge({"figures": ["not-a-row", {"no": "id"}, 42]}, generated)
    assert [f["id"] for f in merged["figures"]] == [gen_id]


def test_merge_safe_to_rerun():
    existing = build(
        [FigureEntry(sha256="a" * 64, width_px=1, height_px=1, origin_relative_path="a.png")]
    )
    generated = build(
        [
            FigureEntry(
                sha256="b" * 64,
                width_px=2,
                height_px=2,
                origin_relative_path="b.png",
                origin_kind="generated",
            )
        ]
    )

    once = merge(existing, generated)
    twice = merge(once, generated)

    assert once == twice
    ids = [f["id"] for f in twice["figures"]]
    assert len(ids) == len(set(ids))
