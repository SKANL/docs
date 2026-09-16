from __future__ import annotations

import copy

from docs.domain.template_validation import validate_template

_BASE = {
    "type": "doc",
    "title": "Doc",
    "sections": [{"id": "intro", "title": "INTRO", "order": 1}],
    "section_contracts": {"intro": {}},
    "context_schema": {"topics": []},
}


def test_template_contract_rejects_invalid_semantic_entries():
    raw = copy.deepcopy(_BASE)
    raw["template_contract"] = {
        "page_geometry": {"width": 0, "margins": {"top": "wide"}},
        "components": [{"kind": ""}, {"kind": "cover"}],
        "editable_slots": [{"id": "title"}, {"id": "title"}],
        "required_assets": [{"id": "logo"}, {"id": "logo"}],
        "fidelity_checks": [{"id": ""}],
        "allowed_degradations": ["", 3],
    }

    issues = validate_template(raw)

    assert any(issue.code == "template.contract.invalid" for issue in issues)
    assert any("page_geometry" in issue.message for issue in issues)
    assert any("editable_slots" in issue.message for issue in issues)


def test_template_contract_accepts_executable_fidelity_shape():
    raw = copy.deepcopy(_BASE)
    raw["template_contract"] = {
        "page_geometry": {"size": "A4", "orientation": "portrait", "margins_cm": {"top": 2.5}},
        "style_contract": {"body_font": "Aptos", "heading_font": "Aptos"},
        "components": [{"id": "cover", "kind": "cover", "required": True}],
        "editable_slots": [{"id": "title", "required": True}],
        "required_assets": [{"id": "logo", "kind": "image", "required": True}],
        "fidelity_checks": [{"id": "page-count", "minimum": 1}],
        "allowed_degradations": ["missing optional preview"],
    }

    assert validate_template(raw) == []
