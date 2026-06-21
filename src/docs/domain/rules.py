from __future__ import annotations

import re

from docs.domain.apa import (
    citation_author_key,
    extract_apa_citations,
    extract_reference_entries,
    reference_author_key,
)
from docs.domain.markdown_text import (
    clean_markdown_text,
    normalize_for_sort,
    strip_frontmatter_and_markdown,
)
from docs.domain.models.template import SectionContract, StrictPolicyBlock, Template
from docs.domain.review import Issue, ReviewResult

_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b")
_EVIDENCE_RE = re.compile(
    r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo|repositorio|c[oó]digo|manifest)\b"
)
_REQUIREMENT_WORD_SPLIT_RE = re.compile(r"\W+")
_QUOTE_RE = re.compile(r'"[^"]{20,}"|“[^”]{20,}”')
_LOCATOR_RE = re.compile(r"\(([^)]*(p\.|pp\.|párr\.|cap\.|sección|tabla)\s*[^)]*)\)", re.IGNORECASE)
_TITLE_RE = re.compile(r"^#\s+\S+", re.MULTILINE)
_RESULTS_RE = re.compile(r"\bresultados?\b")
_RESULTS_EVIDENCE_RE = re.compile(r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo)\b")
_MARGIN_KEYS = ("top", "right", "bottom", "left")
_EXPECTED_MARGIN_CM = 2.5
_MARGIN_TOLERANCE = 0.001


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


def review_apa7_text(text: str, apa7_enabled: bool, strict_policy: StrictPolicyBlock) -> list[Issue]:
    if not apa7_enabled:
        return []

    issues: list[Issue] = []
    severity = strict_policy.apa_violations
    citations = extract_apa_citations(text)
    references = extract_reference_entries(text)

    if citations and not references:
        issues.append(
            Issue(
                severity,
                "Hay citas APA en texto pero no hay lista de referencias detectable.",
                code="apa.no_reference_list",
            )
        )
        for citation in sorted(citations):
            issues.append(
                Issue(severity, f"Cita sin referencia correspondiente: `{citation}`.", code="apa.citation_without_reference")
            )

    if references and not citations:
        for entry in references:
            issues.append(
                Issue(severity, f"Referencia sin cita correspondiente: `{entry[:90]}`.", code="apa.reference_without_citation")
            )

    citation_keys = {citation_author_key(citation) for citation in citations}
    reference_keys = {reference_author_key(entry) for entry in references}

    for citation in sorted(citations):
        key = citation_author_key(citation)
        if key and references and not any(key in ref_key or ref_key in key for ref_key in reference_keys):
            issues.append(
                Issue(severity, f"Cita sin referencia correspondiente: `{citation}`.", code="apa.citation_without_reference")
            )

    for entry in references:
        key = reference_author_key(entry)
        if key and citations and not any(key in cite_key or cite_key in key for cite_key in citation_keys):
            issues.append(
                Issue(severity, f"Referencia sin cita correspondiente: `{entry[:90]}`.", code="apa.reference_without_citation")
            )

    if references and references != sorted(references, key=normalize_for_sort):
        issues.append(
            Issue(severity, "Las referencias no están ordenadas alfabéticamente.", code="apa.references_not_sorted")
        )

    for match in _QUOTE_RE.finditer(text):
        window = text[match.end():match.end() + 90]
        if not _LOCATOR_RE.search(window):
            issues.append(
                Issue(severity, "Cita textual detectada sin localizador APA 7 cercano.", code="apa.quote_without_locator")
            )

    return issues


def review_section_text(
    text: str,
    metadata: dict,
    section_id: str,
    contract: SectionContract,
    template: Template,
    strict: bool,
    *,
    excluded_terms: dict[str, str],
    is_policy_file: bool,
    first_person_patterns: list[str],
    subjective_terms: list[str],
    secret_patterns: list[str],
    scope_term: str = "",
    scope_focus: str = "",
) -> list[Issue]:
    lowered = text.lower()
    issues: list[Issue] = []
    strict_policy = template.strict_policy.strict if strict else template.strict_policy.draft

    if not is_policy_file:
        for term, reason in excluded_terms.items():
            if term in lowered:
                issues.append(
                    Issue(
                        "error",
                        f"Contiene apartado excluido: `{term}`. {reason}".strip(),
                        code="scope.excluded_section",
                    )
                )

    for pattern in first_person_patterns:
        if re.search(pattern, lowered):
            issues.append(
                Issue(
                    "error",
                    f"Contiene primera persona o voz no permitida: patrón `{pattern}`.",
                    code="voice.first_person",
                )
            )

    for term in subjective_terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            issues.append(
                Issue(
                    "warning",
                    f"Contiene término subjetivo sin evidencia automática: `{term}`.",
                    code="voice.subjective_term",
                )
            )

    for pattern in secret_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(
                Issue(
                    "error",
                    f"Contiene posible secreto, credencial o dato sensible: patrón `{pattern}`.",
                    code="privacy.sensitive_data",
                )
            )

    if scope_term and scope_focus and scope_term in lowered and scope_focus not in lowered:
        issues.append(
            Issue(
                "warning",
                f"Menciona `{scope_term}` sin delimitar el alcance a `{scope_focus}`.",
                code="scope.undelimited_ecosystem",
            )
        )

    if not is_policy_file and not _TITLE_RE.search(text):
        issues.append(Issue("error", "La sección no tiene título principal Markdown.", code="structure.missing_title"))

    if contract != SectionContract() and not is_policy_file:
        issues.extend(review_section_contract(text, section_id, contract, strict_policy, strict))

    pending_allowed = strict_policy.allow_pending and contract.pending_allowed_in_draft
    if not is_policy_file and "pendiente" in lowered and not pending_allowed:
        issues.append(
            Issue(
                "error",
                "Contiene PENDIENTE en modo estricto o en una sección que no permite pendientes.",
                code="content.pending_not_allowed",
            )
        )

    issues.extend(review_apa7_text(text, template.apa7.enabled, strict_policy))

    if (
        _RESULTS_RE.search(lowered)
        and "pendiente" not in lowered
        and not _RESULTS_EVIDENCE_RE.search(lowered)
    ):
        issues.append(
            Issue(
                "warning",
                "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                code="evidence.results_without_evidence",
            )
        )

    return issues


def review_rules(
    template: Template, manifest_exists: bool, manifest_size: int, strict: bool = False
) -> ReviewResult:
    issues: list[Issue] = []
    extra = template.model_extra or {}

    if not manifest_exists:
        issues.append(Issue("error" if strict else "warning", "No existe manual-rules.json; ejecuta `build-rules`."))
    elif manifest_size == 0:
        issues.append(Issue("error", "manual-rules.json existe pero está vacío."))

    section_ids = {s.id for s in template.sections}
    contract_ids = set(template.section_contracts)
    missing_contracts = sorted(section_ids - contract_ids)
    if missing_contracts:
        issues.append(Issue("error", f"Faltan contratos de sección: {', '.join(missing_contracts)}."))

    paths = extra.get("paths", {}) or {}
    if paths.get("extracted_dir_policy") != "rules_traceability_only":
        issues.append(Issue("error", "La política de extracted debe ser `rules_traceability_only`."))

    project = extra.get("project", {}) or {}
    if any("tesina/extracted" in source for source in project.get("source_priority", [])):
        issues.append(Issue("error", "`tesina/extracted` no debe aparecer en source_priority como fuente activa."))

    if not template.apa7.enabled:
        issues.append(Issue("error", "APA 7 debe estar habilitado."))

    preliminaries = extra.get("preliminaries", {}) or {}
    if not preliminaries.get("roman_pagination", {}).get("enabled"):
        issues.append(Issue("error", "La paginación romana de preliminares debe estar habilitada."))
    if preliminaries.get("body_pagination_start", {}).get("section_id") != "introduccion":
        issues.append(Issue("error", "La paginación arábiga debe iniciar en INTRODUCCIÓN."))

    margin_contract = (extra.get("format", {}) or {}).get("page_margins_cm", {}) or {}
    non_cover_margins = margin_contract.get("non_cover", {}) or {}
    bad_margins = [
        key
        for key in _MARGIN_KEYS
        if not isinstance(non_cover_margins.get(key), (int, float))
        or abs(float(non_cover_margins.get(key)) - _EXPECTED_MARGIN_CM) > _MARGIN_TOLERANCE
    ]
    if margin_contract.get("cover_policy") != "preserve_template":
        issues.append(
            Issue("error", "La portada debe conservar el formato y márgenes de la plantilla (`preserve_template`).")
        )
    if bad_margins:
        issues.append(Issue("error", "El contrato de layout debe fijar márgenes de 2.5 cm en toda sección no-portada."))

    active_overrides = {
        item.get("id") for item in extra.get("advisor_overrides", []) if item.get("status") == "active"
    }
    if "margins-2-5cm-non-cover" not in active_overrides:
        issues.append(Issue("error", "Falta el advisor_override activo para márgenes de 2.5 cm excepto portada."))

    for section_id, contract in template.section_contracts.items():
        if not contract.required_content:
            issues.append(Issue("error", f"El contrato `{section_id}` no define contenido obligatorio."))
        # Duplicates the document-level APA gate above when both fire — this is
        # real legacy behavior (review_rules never deduplicates), preserve it.
        if contract.apa_required and not template.apa7.enabled:
            issues.append(Issue("error", f"El contrato `{section_id}` requiere APA pero APA 7 está deshabilitado."))

    return ReviewResult(issues)
