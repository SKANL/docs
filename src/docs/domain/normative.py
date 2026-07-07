from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Document-type normative writing-pattern lexicons (excluded front matter,
# first-person voice patterns, subjective terms) are evacuated to template
# data (spec: document-template "No hardcoded document-type literal in
# domain code") -- every document type MUST declare its own `normative` block
# in its template. These defaults are intentionally EMPTY: an absent
# declaration means no lexicon is enforced, never a hardcoded Spanish-thesis
# fallback. `reporte-estadia-tic.json` already declares its own equivalent
# blocks explicitly, so runtime behavior for that document type is
# byte-identical (see `tests/unit/domain/test_rules_characterization.py`).
EXCLUDED_FRONT_MATTER: dict[str, str] = {}

FIRST_PERSON_PATTERNS: list[str] = []

SUBJECTIVE_TERMS: list[str] = []

SECRET_PATTERNS: list[str] = [
    r"\bapi[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bsecret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bpassword\s*[:=]\s*['\"]?[^'\"\s]{8,}",
    r"\btoken\s*[:=]\s*['\"]?[A-Za-z0-9_\-.]{24,}",
]


@dataclass(frozen=True)
class NormativeSettings:
    """Bundles the 7 normative kwargs review_section_text/review_document/
    review_section/pack_context(_document) each required loose before Slice
    16. Built by resolve_normative_settings(config); downstream code passes
    the whole object instead of unpacking 7 parameters at every call site
    (Slice 16 tech-debt remediation, finding 4)."""

    excluded_terms: dict[str, str]
    is_policy_file: bool
    first_person_patterns: list[str]
    subjective_terms: list[str]
    secret_patterns: list[str]
    scope_term: str = ""
    scope_focus: str = ""


def resolve_normative_settings(config: dict[str, Any]) -> NormativeSettings:
    """Extrae las kwargs normativas que review_section_text/review_document/
    pack_context(_document) requieren, con los mismos defaults que legacy
    review_section (1455-1458, 1473, 1477-1478). is_policy_file no se
    resuelve aquí: en este código base siempre es False en este punto de
    llamada (confirmado en la revisión previa a la ejecución de Slice 5)."""
    normative = config.get("normative", {})
    excluded = normative.get("excluded_front_matter", EXCLUDED_FRONT_MATTER)
    excluded_terms = excluded if isinstance(excluded, dict) else {term: "" for term in excluded}
    return NormativeSettings(
        excluded_terms=excluded_terms,
        is_policy_file=False,
        first_person_patterns=normative.get("first_person_patterns", FIRST_PERSON_PATTERNS),
        subjective_terms=normative.get("subjective_terms", SUBJECTIVE_TERMS),
        secret_patterns=SECRET_PATTERNS + list(config.get("privacy", {}).get("forbidden_in_body_patterns", [])),
        scope_term=normative.get("scope_term", ""),
        scope_focus=normative.get("scope_focus", ""),
    )
