from __future__ import annotations

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
