# tests/unit/domain/test_docx_structure.py
from docs.domain.docx_structure import (
    DEFAULT_RESPONSIBILITY_TEXT,
    margins_match,
    non_cover_margin_emu,
    resolve_part_text,
    sections_index,
    structure_parts,
)


def test_structure_parts_uses_explicit_structure_when_present():
    config = {"structure": [{"type": "cover_from_template"}]}
    assert structure_parts(config) == [{"type": "cover_from_template"}]


def test_structure_parts_synthesizes_cover_when_preliminaries_absent():
    assert structure_parts({}) == [
        {"type": "cover_from_template"},
        {
            "type": "sections",
            "preliminary_pagination": {},
            "body_restart_section": "",
            "body_pagination": {"format": "decimal", "start": 1},
        },
    ]


def test_structure_parts_includes_blank_page_when_enabled():
    config = {"preliminaries": {"blank_page": {"enabled": True}}}
    parts = structure_parts(config)
    assert {"type": "blank_page"} in parts


def test_structure_parts_omits_blank_page_when_not_enabled():
    config = {"preliminaries": {"blank_page": {"enabled": False}}}
    parts = structure_parts(config)
    assert {"type": "blank_page"} not in parts


def test_structure_parts_includes_responsibility_page_with_default_text_fallback():
    config = {"preliminaries": {"responsibility_page": {"enabled": True}}}
    parts = structure_parts(config)
    fixed_text_parts = [p for p in parts if p["type"] == "fixed_text_page"]
    assert fixed_text_parts == [{"type": "fixed_text_page", "text": DEFAULT_RESPONSIBILITY_TEXT}]


def test_structure_parts_includes_responsibility_page_with_explicit_text():
    config = {
        "preliminaries": {
            "responsibility_page": {"enabled": True, "text": "Texto personalizado."}
        }
    }
    parts = structure_parts(config)
    fixed_text_parts = [p for p in parts if p["type"] == "fixed_text_page"]
    assert fixed_text_parts == [{"type": "fixed_text_page", "text": "Texto personalizado."}]


def test_structure_parts_sets_roman_pagination_when_enabled():
    config = {"preliminaries": {"roman_pagination": {"enabled": True}}}
    parts = structure_parts(config)
    sections_part = next(p for p in parts if p["type"] == "sections")
    assert sections_part["preliminary_pagination"] == {"format": "lowerRoman", "start": 2}


def test_structure_parts_uses_blank_page_start_for_roman_pagination():
    config = {
        "preliminaries": {
            "roman_pagination": {"enabled": True},
            "blank_page": {"start": 3},
        }
    }
    parts = structure_parts(config)
    sections_part = next(p for p in parts if p["type"] == "sections")
    assert sections_part["preliminary_pagination"] == {"format": "lowerRoman", "start": 3}


def test_structure_parts_sets_body_restart_section_and_pagination():
    config = {
        "preliminaries": {
            "body_pagination_start": {"section_id": "body", "format": "decimal", "start": 5}
        }
    }
    parts = structure_parts(config)
    sections_part = next(p for p in parts if p["type"] == "sections")
    assert sections_part["body_restart_section"] == "body"
    assert sections_part["body_pagination"] == {"format": "decimal", "start": 5}


def test_resolve_part_text_returns_literal_text_first():
    assert resolve_part_text({}, {"text": "literal"}) == "literal"


def test_resolve_part_text_resolves_text_field_from_project():
    config = {"project": {"institution": "UTN"}}
    assert resolve_part_text(config, {"text_field": "institution"}) == "UTN"


def test_resolve_part_text_returns_empty_when_neither_present():
    assert resolve_part_text({}, {}) == ""


def test_resolve_part_text_returns_empty_when_text_field_not_in_project():
    config = {"project": {}}
    assert resolve_part_text(config, {"text_field": "missing"}) == ""


def test_non_cover_margin_emu_converts_cm_to_emu():
    config = {
        "format": {
            "page_margins_cm": {
                "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5}
            }
        }
    }
    expected = non_cover_margin_emu(config)
    assert expected == {"top": 900000, "right": 900000, "bottom": 900000, "left": 900000}


def test_non_cover_margin_emu_matches_python_docx_cm_conversion():
    from docx.shared import Cm

    config = {"format": {"page_margins_cm": {"non_cover": {"top": 2.5}}}}
    assert non_cover_margin_emu(config)["top"] == int(Cm(2.5))


def test_non_cover_margin_emu_skips_non_numeric_values():
    config = {"format": {"page_margins_cm": {"non_cover": {"top": "invalid"}}}}
    assert non_cover_margin_emu(config) == {}


def test_non_cover_margin_emu_returns_empty_dict_when_no_margins_configured():
    assert non_cover_margin_emu({}) == {}


def test_margins_match_true_within_tolerance():
    assert margins_match({"top": 900005}, {"top": 900000}) is True


def test_margins_match_false_outside_tolerance():
    assert margins_match({"top": 950000}, {"top": 900000}) is False


def test_margins_match_false_when_key_missing_from_actual():
    assert margins_match({}, {"top": 900000}) is False


def test_margins_match_true_when_expected_is_empty():
    assert margins_match({"top": 1}, {}) is True


# --- Task 8.4/8.5: single shared _sections_index implementation ---------
#
# `DocxRendererAdapter` (application layer) and `PythonDocxAssemblyAdapter`
# (infrastructure layer) each used to carry their own byte-identical private
# `_sections_index` method. Both now delegate to this one domain-layer
# function instead.


def test_sections_index_locates_the_sections_part():
    parts = [{"type": "cover_from_template"}, {"type": "sections"}, {"type": "embed_docx"}]
    assert sections_index(parts) == 1


def test_sections_index_defaults_to_end_when_no_sections_part_present():
    assert sections_index([{"type": "cover_from_template"}]) == 1


def test_sections_index_is_the_single_shared_implementation():
    from docs.application.docx_assembly import DocxRendererAdapter
    from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter

    assert not hasattr(DocxRendererAdapter, "_sections_index")
    assert not hasattr(PythonDocxAssemblyAdapter, "_sections_index")
