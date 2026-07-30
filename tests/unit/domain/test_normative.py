from __future__ import annotations

import pytest

from docs.domain.normative import (
    EXCLUDED_FRONT_MATTER,
    FIRST_PERSON_PATTERNS,
    SECRET_PATTERNS,
    SUBJECTIVE_TERMS,
    NormativeSettings,
    resolve_normative_settings,
)


def test_resolve_normative_settings_uses_defaults_when_config_is_empty():
    settings = resolve_normative_settings({})
    assert settings.excluded_terms == EXCLUDED_FRONT_MATTER
    assert settings.first_person_patterns == FIRST_PERSON_PATTERNS
    assert settings.subjective_terms == SUBJECTIVE_TERMS
    assert settings.secret_patterns == SECRET_PATTERNS
    assert settings.is_policy_file is False
    assert settings.scope_term == ""
    assert settings.scope_focus == ""


def test_resolve_normative_settings_overrides_from_config():
    config = {
        "normative": {
            "excluded_front_matter": {"anexo": "fuera de alcance"},
            "first_person_patterns": [r"\byo\b"],
            "subjective_terms": ["genial"],
            "scope_term": "ecosistema",
            "scope_focus": "app móvil",
        }
    }
    settings = resolve_normative_settings(config)
    assert settings.excluded_terms == {"anexo": "fuera de alcance"}
    assert settings.first_person_patterns == [r"\byo\b"]
    assert settings.subjective_terms == ["genial"]
    assert settings.scope_term == "ecosistema"
    assert settings.scope_focus == "app móvil"


def test_resolve_normative_settings_converts_list_excluded_front_matter_to_dict():
    config = {"normative": {"excluded_front_matter": ["portada", "anexo"]}}
    settings = resolve_normative_settings(config)
    assert settings.excluded_terms == {"portada": "", "anexo": ""}


def test_resolve_normative_settings_appends_privacy_forbidden_patterns_to_secret_patterns():
    config = {"privacy": {"forbidden_in_body_patterns": [r"\bdni\s*[:=]\s*\d{7,8}"]}}
    settings = resolve_normative_settings(config)
    assert settings.secret_patterns == SECRET_PATTERNS + [r"\bdni\s*[:=]\s*\d{7,8}"]


def test_resolve_normative_settings_returns_normative_settings_instance():
    config = {"normative": {}, "privacy": {}}
    result = resolve_normative_settings(config)
    assert isinstance(result, NormativeSettings)
    assert result.is_policy_file is False
    assert result.scope_term == ""


def test_resolve_normative_settings_reads_overrides_from_config():
    config = {
        "normative": {
            "excluded_front_matter": {"anexo": "excluido"},
            "first_person_patterns": [r"\bnosotros\b"],
            "subjective_terms": ["genial"],
            "scope_term": "aws",
            "scope_focus": "backend",
        },
        "privacy": {"forbidden_in_body_patterns": [r"\bsecreto-interno\b"]},
    }
    result = resolve_normative_settings(config)
    assert result.excluded_terms == {"anexo": "excluido"}
    assert result.first_person_patterns == [r"\bnosotros\b"]
    assert result.subjective_terms == ["genial"]
    assert result.scope_term == "aws"
    assert result.scope_focus == "backend"
    assert r"\bsecreto-interno\b" in result.secret_patterns


def test_resolve_normative_settings_contested_stack_terms_defaults_empty():
    settings = resolve_normative_settings({})
    assert settings.contested_stack_terms == []


def test_resolve_normative_settings_reads_contested_stack_terms_from_cross_consistency():
    config = {"cross_consistency": {"contested_stack_terms": ["Laravel", "Supabase"]}}
    settings = resolve_normative_settings(config)
    assert settings.contested_stack_terms == ["Laravel", "Supabase"]


def test_resolve_normative_settings_citation_style_defaults_apa7():
    settings = resolve_normative_settings({})
    assert settings.citation_style == "apa7"


def test_resolve_normative_settings_citation_style_reads_none_from_apa7_block():
    config = {"apa7": {"citation_style": "none"}}
    settings = resolve_normative_settings(config)
    assert settings.citation_style == "none"


def test_resolve_normative_settings_citation_style_rejects_unknown_value():
    config = {"apa7": {"citation_style": "mla9"}}
    with pytest.raises(ValueError, match="citation_style"):
        resolve_normative_settings(config)
