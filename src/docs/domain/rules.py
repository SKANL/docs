from __future__ import annotations

import re

from docs.domain.apa import extract_apa_citations
from docs.domain.markdown_text import clean_markdown_text, strip_frontmatter_and_markdown
from docs.domain.models.template import SectionContract, StrictPolicyBlock
from docs.domain.review import Issue

_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b")
_EVIDENCE_RE = re.compile(
    r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo|repositorio|c[oó]digo|manifest)\b"
)
_REQUIREMENT_WORD_SPLIT_RE = re.compile(r"\W+")


def requirement_present(requirement: str, plain: str, detect: dict[str, list[str]]) -> bool:
    candidates = detect.get(requirement)
    if not candidates:
        words = [w for w in _REQUIREMENT_WORD_SPLIT_RE.split(requirement.lower()) if len(w) >= 4]
        candidates = [requirement] + words
    return any(str(candidate).lower() in plain for candidate in candidates)


def review_section_contract(
    text: str,
    section_id: str,
    contract: SectionContract,
    strict_policy: StrictPolicyBlock,
    strict: bool,
) -> list[Issue]:
    issues: list[Issue] = []
    plain = clean_markdown_text(text).lower()
    word_count = len(_WORD_RE.findall(strip_frontmatter_and_markdown(text)))

    length_severity = strict_policy.length_violations
    if contract.length.min_words and word_count < contract.length.min_words:
        issues.append(
            Issue(
                length_severity,
                f"La sección `{section_id}` tiene {word_count} palabras; "
                f"mínimo esperado: {contract.length.min_words}.",
                code="contract.length_below_min",
            )
        )
    if contract.length.max_words and word_count > contract.length.max_words:
        issues.append(
            Issue(
                length_severity,
                f"La sección `{section_id}` tiene {word_count} palabras; "
                f"máximo esperado: {contract.length.max_words}.",
                code="contract.length_above_max",
            )
        )

    missing = [
        requirement
        for requirement in contract.required_content
        if not requirement_present(requirement, plain, contract.detect)
    ]
    if missing:
        # Legacy quirk (intentional, not a bug): this check uses the raw `strict`
        # flag directly, NOT `strict_policy.missing_required` — there is no such
        # strict_policy field for this check in legacy. Every other check in this
        # function resolves severity via strict_policy; this one does not.
        severity = "error" if strict else "warning"
        issues.append(
            Issue(
                severity,
                f"No se detecta contenido obligatorio de `{section_id}`: {', '.join(missing)}.",
                code="contract.missing_required",
            )
        )

    if contract.evidence_required:
        has_pending = "pendiente" in plain
        has_evidence = bool(_EVIDENCE_RE.search(plain))
        if not has_pending and not has_evidence:
            issues.append(
                Issue(
                    strict_policy.missing_evidence,
                    f"`{section_id}` requiere evidencia o marcador PENDIENTE.",
                    code="evidence.required",
                )
            )

    if contract.apa_required and not extract_apa_citations(text) and "pendiente" not in plain:
        issues.append(
            Issue(
                strict_policy.apa_violations,
                f"`{section_id}` requiere citas APA 7 o marcador PENDIENTE.",
                code="apa.required",
            )
        )

    return issues
