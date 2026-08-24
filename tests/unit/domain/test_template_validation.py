# tests/unit/domain/test_template_validation.py
"""Unit coverage for domain/template_validation.py (design.md Decision 1b,
spec: document-template "Template Structural and Completeness Validation").
`validate_template(raw: dict) -> list[Issue]` operates on the RAW dict (not
a pre-parsed Template) so structurally-invalid input never has to survive a
pydantic parse first, and completeness (TODO/null sentinels from `template
init`) is checked independently of validity."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from docs.domain.template_validation import validate_template

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "templates"

_MINIMAL_VALID = {
    "type": "doc",
    "title": "Doc",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
    "section_contracts": {"introduccion": {"required_content": ["objetivo"]}},
    "context_schema": {"topics": [{"id": "alumno", "title": "Alumno"}]},
}


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_minimal_valid_template_passes_with_no_issues():
    assert validate_template(_MINIMAL_VALID) == []


def test_reporte_estadia_tic_fixture_passes():
    assert validate_template(_load_fixture("reporte-estadia-tic.json")) == []


def test_documento_generico_fixture_passes():
    assert validate_template(_load_fixture("documento-generico.json")) == []


def test_missing_required_top_level_block_is_named():
    raw = copy.deepcopy(_MINIMAL_VALID)
    del raw["section_contracts"]

    issues = validate_template(raw)

    assert any("section_contracts" in issue.message for issue in issues)
    assert all(issue.severity == "error" for issue in issues)


def test_section_without_matching_contract_is_named():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["sections"].append({"id": "conclusiones", "title": "Conclusiones", "order": 2})

    issues = validate_template(raw)

    assert any("conclusiones" in issue.message for issue in issues)


def test_duplicate_topic_ids_are_named():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["context_schema"]["topics"].append({"id": "alumno", "title": "Alumno otra vez"})

    issues = validate_template(raw)

    assert any("alumno" in issue.message for issue in issues)


def test_body_pagination_start_referencing_unknown_section_is_named():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["preliminaries"] = {"body_pagination_start": {"section_id": "no-existe"}}

    issues = validate_template(raw)

    assert any("no-existe" in issue.message for issue in issues)


def test_non_numeric_margin_is_rejected_with_named_field():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["format"] = {"page_margins_cm": {"non_cover": {"top": "not-a-number", "right": 2.5, "bottom": 2.5, "left": 2.5}}}

    issues = validate_template(raw)

    assert any("top" in issue.message for issue in issues)


def test_unknown_extension_keys_are_tolerated():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["some_future_extension"] = {"anything": "goes"}

    assert validate_template(raw) == []


def test_incomplete_skeleton_with_todo_sentinel_is_rejected_naming_the_field():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["title"] = "TODO"

    issues = validate_template(raw)

    assert any("title" in issue.message for issue in issues)


def test_incomplete_skeleton_with_null_sentinel_is_rejected_naming_the_field():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["sections"][0]["title"] = None

    issues = validate_template(raw)

    assert any("sections" in issue.message and "title" in issue.message for issue in issues)


def test_comment_sibling_keys_are_never_treated_as_incomplete():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["$comment"] = None
    raw["sections"][0]["$comment"] = "TODO"

    assert validate_template(raw) == []


# --- the typo net: a near-miss key is a silently-dead rule --------------------


def test_a_near_miss_contract_key_is_reported_with_the_field_it_meant():
    # THE expensive failure mode: models are permissive on purpose (see
    # models/template.py), so `required_contents` (plural) was accepted,
    # silently ignored, and the author's rule simply never ran. The template
    # validated. The document built. Nothing failed.
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["section_contracts"]["introduccion"] = {"required_contents": ["objetivo"]}

    issues = validate_template(raw)

    near_miss = [i for i in issues if i.code == "template.unknown_key"]
    assert len(near_miss) == 1, issues
    assert "required_contents" in near_miss[0].message
    assert "required_content" in near_miss[0].message
    assert near_miss[0].severity == "warning", "no bloquea: la clave puede ser passthrough deliberado"


def test_near_miss_keys_are_reported_at_every_nesting_level():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["sections"][0]["ordre"] = 1
    raw["context_schema"]["topics"][0]["consumedby"] = ["introduccion"]
    raw["apa7"] = {"citation_stile": "none"}

    messages = " ".join(i.message for i in validate_template(raw) if i.code == "template.unknown_key")

    assert "ordre" in messages and "order" in messages
    assert "consumedby" in messages and "consumed_by" in messages
    assert "citation_stile" in messages and "citation_style" in messages


def test_a_deliberate_passthrough_key_is_left_alone():
    # `custom_legacy_key` resembles no real field, so it is an intentional
    # untyped passthrough — it survives into the rendered context pack and
    # must not be nagged about. Precision is what makes this net usable.
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["section_contracts"]["introduccion"]["custom_legacy_key"] = "valor"

    assert [i for i in validate_template(raw) if i.code == "template.unknown_key"] == []


def test_comment_siblings_are_never_reported_as_near_misses():
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw["$comment"] = "documentación inline"
    raw["sections"][0]["$comment"] = "nota"
    raw["_note"] = "otra nota"

    assert [i for i in validate_template(raw) if i.code == "template.unknown_key"] == []


def test_the_config_envelope_blocks_are_never_reported_as_near_misses():
    # Every builtin template ships `format`/`paths`/`normative`/... at top
    # level. They are the config envelope, not typos.
    raw = copy.deepcopy(_MINIMAL_VALID)
    raw.update({"format": {}, "paths": {}, "normative": {}, "privacy": {}, "output": {}})

    assert [i for i in validate_template(raw) if i.code == "template.unknown_key"] == []
