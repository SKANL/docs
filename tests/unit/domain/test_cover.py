from __future__ import annotations

from docs.domain.cover import (
    CoverMode,
    CoverSpec,
    CoverVariant,
    cover_asset_findings,
    cover_findings,
    resolve_cover_slots,
    resolve_cover_spec,
)


def test_cover_spec_resolves_declared_slots_and_defaults_deterministically():
    spec = CoverSpec(
        mode=CoverMode.GENERATED,
        variant=CoverVariant.ACADEMIC,
        slots={"title": "{{title}}", "author": "{{project.author}}", "degree": "BSc"},
    )

    resolved = resolve_cover_slots(spec, {"title": "Native Covers", "project": {"author": "Ada"}})

    assert list(resolved.items()) == [("title", "Native Covers"), ("author", "Ada"), ("degree", "BSc")]


def test_cover_spec_uses_default_title_slot_when_slots_are_omitted():
    assert resolve_cover_slots(CoverSpec(), {"title": "Fallback title"}) == {"title": "Fallback title"}


def test_generated_cover_html_escapes_slots_and_exposes_variant():
    from docs.domain.cover import render_cover_html

    html = render_cover_html(
        CoverSpec(slots={"title": "{{title}}"}),
        {"title": "A < B"},
    )

    assert '<header class="cover cover--academic" role="banner">' in html
    assert 'class="cover__slot cover__title"' in html
    assert "A &lt; B" in html


def test_cover_provenance_records_variant_and_unresolved_slots():
    from docs.domain.cover import cover_provenance

    result = cover_provenance(
        {
            "cover": {
                "mode": "generated",
                "variant": "technical",
                "slots": {"title": "{{title}}", "owner": "{{project.owner}}"},
            },
            "title": "Report",
        }
    )

    assert result == {"mode": "generated", "variant": "technical", "missing_slots": ["owner"]}


def test_format_cover_is_canonical_and_supports_content_page_visual_and_layout():
    spec = resolve_cover_spec(
        {
            "title": "Report",
            "format": {
                "cover": {
                    "mode": "generated",
                    "variant": "custom",
                    "content": {"author": "{{project.owner}}"},
                    "page": {"size": "letter", "margins_cm": {"top": 2}},
                    "visual": {"accent_color": "#123456"},
                    "layout": {"alignment": "left", "title_size_pt": 28},
                }
            },
            "project": {"owner": "Ada"},
        }
    )

    assert spec is not None
    assert spec.mode is CoverMode.GENERATED
    assert spec.variant is CoverVariant.CUSTOM
    assert spec.content["author"] == "{{project.owner}}"
    assert spec.page["size"] == "letter"
    assert spec.visual["accent_color"] == "#123456"
    assert spec.layout["alignment"] == "left"


def test_explicit_none_mode_is_preserved_and_absent_cover_is_distinct():
    none_spec = resolve_cover_spec({"format": {"cover": {"mode": "none"}}})

    assert none_spec is not None
    assert none_spec.mode is CoverMode.NONE
    assert resolve_cover_spec({}) is None


def test_missing_standard_cover_paths_produce_clear_findings():
    spec = CoverSpec(content={"author": "{{project.owner}}", "title": "{{title}}"})

    assert cover_findings(spec, {"title": "Report"}) == ["cover.missing_slot: author"]


def test_cover_content_wins_over_current_slots_and_resolves_standard_sources():
    spec = CoverSpec(
        content={"title": "{{document.title}}", "author": "{{author.name}}"},
        slots={"title": "current title", "author": "current author"},
    )

    resolved = resolve_cover_slots(
        spec,
        {
            "title": "Top-level title",
            "metadata": {"title": "Metadata title"},
            "context": {"alumno": {"nombre": "Ada Lovelace"}},
        },
    )

    assert resolved == {"title": "Top-level title", "author": "Ada Lovelace"}


def test_cover_asset_findings_report_missing_and_zero_dimension_assets(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    spec = CoverSpec(visual={"logo": "missing.png", "hero": "empty.png"})

    findings = cover_asset_findings(spec, {"paths": {"assets_dir": str(tmp_path)}})

    assert findings == [
        "cover.missing_asset: logo",
        "cover.invalid_asset: hero",
    ]


def test_cover_html_projects_valid_configured_images_with_alt_text(tmp_path):
    logo = tmp_path / "logo.png"
    from PIL import Image

    Image.new("RGB", (12, 8), "navy").save(logo)
    spec = CoverSpec(visual={"logo": "logo.png"}, content={"title": "Report"})

    from docs.domain.cover import render_cover_html

    html = render_cover_html(spec, {"paths": {"assets_dir": str(tmp_path)}})

    assert 'class="cover__image cover__logo"' in html
    assert 'alt="logo"' in html
    assert str(logo).replace("\\", "/") in html
