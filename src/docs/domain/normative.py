from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EXCLUDED_FRONT_MATTER: dict[str, str] = {
    "portada": "La portada se toma desde la plantilla DOCX, no se redacta como sección.",
    "hoja de guarda": "La hoja de guarda está excluida del arnés.",
    "carta responsiva": "La carta responsiva está excluida del arnés.",
    "carta de liberación": "Las cartas de liberación están excluidas del arnés.",
    "carta de liberacion": "Las cartas de liberación están excluidas del arnés.",
}

FIRST_PERSON_PATTERNS: list[str] = [
    r"\byo\b",
    r"\bnosotros\b",
    r"\bnosotras\b",
    r"\bmi\b",
    r"\bmis\b",
    r"\bnuestro\b",
    r"\bnuestra\b",
    r"\bdesarrollé\b",
    r"\bdesarrollamos\b",
    r"\bconsidero\b",
    r"\bcreemos\b",
]

SUBJECTIVE_TERMS: list[str] = [
    "excelente",
    "impresionante",
    "increíble",
    "increible",
    "claramente",
    "obviamente",
    "afortunadamente",
    "lamentablemente",
    "simplemente",
    "éxito",
    "exito",
    "fracaso",
]

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


def resolve_normative_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extrae las kwargs normativas que review_section_text/review_document/
    pack_context(_document) requieren, con los mismos defaults que legacy
    review_section (1455-1458, 1473, 1477-1478). is_policy_file no se
    resuelve aquí: en este código base siempre es False en este punto de
    llamada (confirmado en la revisión previa a la ejecución de Slice 5)."""
    normative = config.get("normative", {})
    excluded = normative.get("excluded_front_matter", EXCLUDED_FRONT_MATTER)
    excluded_terms = excluded if isinstance(excluded, dict) else {term: "" for term in excluded}
    return {
        "excluded_terms": excluded_terms,
        "is_policy_file": False,
        "first_person_patterns": normative.get("first_person_patterns", FIRST_PERSON_PATTERNS),
        "subjective_terms": normative.get("subjective_terms", SUBJECTIVE_TERMS),
        "secret_patterns": SECRET_PATTERNS + list(config.get("privacy", {}).get("forbidden_in_body_patterns", [])),
        "scope_term": normative.get("scope_term", ""),
        "scope_focus": normative.get("scope_focus", ""),
    }
