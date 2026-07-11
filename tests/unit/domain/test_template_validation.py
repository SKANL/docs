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
