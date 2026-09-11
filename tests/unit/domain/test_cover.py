from __future__ import annotations

from docs.domain.cover import (
    CoverMode,
    CoverSpec,
    CoverVariant,
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

    assert 'class="docs-cover docs-cover--academic"' in html
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
