from __future__ import annotations

import re
from typing import Any

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
from docs.domain.normative import NormativeSettings
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

# CRITICAL-1 (verify-report-pr6.md): section_rendering.render_contract_scaffold
# emits exactly three fixed PENDIENTE placeholder sentence templates -- e.g.
# "PENDIENTE: documentar {item} con evidencia del ledger, contexto o fuentes."
# -- which embed a required_content item's own words in its own "not yet
# done" text, trivially self-satisfying requirement_present's substring
# check. Stripped by their known opening verb before the presence check so a
# freshly-scaffolded, unedited section can never self-satisfy its own
# required_content (root-cause fix in the shared function -- fixes every
# caller: review_section_contract AND ContextService.build_gap_report).
# ponytail: verb-anchored, not "any PENDIENTE: sentence" -- a human/AI note
# like "PENDIENTE: aún no hay resultados." (different opening verb) still
# counts as present, preserving detect overrides like the estadía
# "resultados importantes o PENDIENTE" -> ["resultado", "pendiente"] escape
# hatch. Upgrade path if this ever collides: track generated-text provenance
# instead of pattern-matching the harness's own wording.
_SCAFFOLD_PENDIENTE_RE = re.compile(r"pendiente:\s*(?:documentar|agregar citas|ordenar)[^.]*\.")


def requirement_present(requirement: str, plain: str, detect: dict[str, list[str]]) -> bool:
    scrubbed = _SCAFFOLD_PENDIENTE_RE.sub(" ", plain)
    candidates = detect.get(requirement)
    if not candidates:
        words = [w for w in _REQUIREMENT_WORD_SPLIT_RE.split(requirement.lower()) if len(w) >= 4]
        candidates = [requirement] + words
    return any(str(candidate).lower() in scrubbed for candidate in candidates)


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


def _check_excluded_terms(lowered: str, is_policy_file: bool, excluded_terms: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
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
    return issues


def _check_first_person(lowered: str, first_person_patterns: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for pattern in first_person_patterns:
        if re.search(pattern, lowered):
            issues.append(
                Issue(
                    "error",
                    f"Contiene primera persona o voz no permitida: patrón `{pattern}`.",
                    code="voice.first_person",
                )
            )
    return issues


def _check_subjective_terms(lowered: str, subjective_terms: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for term in subjective_terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            issues.append(
                Issue(
                    "warning",
                    f"Contiene término subjetivo sin evidencia automática: `{term}`.",
                    code="voice.subjective_term",
                )
            )
    return issues


def _check_secret_patterns(text: str, secret_patterns: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for pattern in secret_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(
                Issue(
                    "error",
                    f"Contiene posible secreto, credencial o dato sensible: patrón `{pattern}`.",
                    code="privacy.sensitive_data",
                )
            )
    return issues


def _check_scope_delimitation(lowered: str, scope_term: str, scope_focus: str) -> list[Issue]:
    if scope_term and scope_focus and scope_term in lowered and scope_focus not in lowered:
        return [
            Issue(
                "warning",
                f"Menciona `{scope_term}` sin delimitar el alcance a `{scope_focus}`.",
                code="scope.undelimited_ecosystem",
            )
        ]
    return []


def _check_title(text: str, is_policy_file: bool) -> list[Issue]:
    if not is_policy_file and not _TITLE_RE.search(text):
        return [Issue("error", "La sección no tiene título principal Markdown.", code="structure.missing_title")]
    return []


def _check_contract_dispatch(
    text: str, section_id: str, contract: SectionContract, strict_policy: StrictPolicyBlock, strict: bool, is_policy_file: bool
) -> list[Issue]:
    if contract != SectionContract() and not is_policy_file:
        return review_section_contract(text, section_id, contract, strict_policy, strict)
    return []


def _check_pending_marker(lowered: str, is_policy_file: bool, strict_policy: StrictPolicyBlock, contract: SectionContract) -> list[Issue]:
    pending_allowed = strict_policy.allow_pending and contract.pending_allowed_in_draft
    if not is_policy_file and "pendiente" in lowered and not pending_allowed:
        return [
            Issue(
                "error",
                "Contiene PENDIENTE en modo estricto o en una sección que no permite pendientes.",
                code="content.pending_not_allowed",
            )
        ]
    return []


def _check_results_evidence(lowered: str) -> list[Issue]:
    if _RESULTS_RE.search(lowered) and "pendiente" not in lowered and not _RESULTS_EVIDENCE_RE.search(lowered):
        return [
            Issue(
                "warning",
                "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                code="evidence.results_without_evidence",
            )
        ]
    return []


def review_section_text(
    text: str,
    metadata: dict,
    section_id: str,
    contract: SectionContract,
    template: Template,
    strict: bool,
    *,
    normative: NormativeSettings,
) -> list[Issue]:
    lowered = text.lower()
    strict_policy = template.strict_policy.strict if strict else template.strict_policy.draft
    issues: list[Issue] = []

    issues.extend(_check_excluded_terms(lowered, normative.is_policy_file, normative.excluded_terms))
    issues.extend(_check_first_person(lowered, normative.first_person_patterns))
    issues.extend(_check_subjective_terms(lowered, normative.subjective_terms))
    issues.extend(_check_secret_patterns(text, normative.secret_patterns))
    issues.extend(_check_scope_delimitation(lowered, normative.scope_term, normative.scope_focus))
    issues.extend(_check_title(text, normative.is_policy_file))
    issues.extend(_check_contract_dispatch(text, section_id, contract, strict_policy, strict, normative.is_policy_file))
    issues.extend(_check_pending_marker(lowered, normative.is_policy_file, strict_policy, contract))
    issues.extend(review_apa7_text(text, template.apa7.enabled, strict_policy))
    issues.extend(_check_results_evidence(lowered))

    return issues


def _check_manifest_state(manifest_exists: bool, manifest_size: int, strict: bool) -> list[Issue]:
    issues: list[Issue] = []
    if not manifest_exists:
        issues.append(Issue("error" if strict else "warning", "No existe manual-rules.json; ejecuta `build-rules`."))
    elif manifest_size == 0:
        issues.append(Issue("error", "manual-rules.json existe pero está vacío."))
    return issues


def _check_missing_section_contracts(template: Template) -> list[Issue]:
    section_ids = {s.id for s in template.sections}
    contract_ids = set(template.section_contracts)
    missing_contracts = sorted(section_ids - contract_ids)
    if missing_contracts:
        return [Issue("error", f"Faltan contratos de sección: {', '.join(missing_contracts)}.")]
    return []


def _check_extracted_dir_policy(extra: dict[str, Any]) -> list[Issue]:
    """Fires only when `paths.extracted_dir` is configured (mirrors
    `doctor.py`'s own gating). Validates that a policy governing that path is
    actually declared -- never compares the declared value against a
    hardcoded expected literal (spec: document-pipeline "Extracted-dir policy
    checked only when configured")."""
    paths = extra.get("paths", {}) or {}
    if not paths.get("extracted_dir"):
        return []
    policy = paths.get("extracted_dir_policy")
    if not policy or not isinstance(policy, str):
        return [
            Issue(
                "error",
                "Debe declararse `paths.extracted_dir_policy` (texto) cuando "
                "`paths.extracted_dir` está configurado.",
            )
        ]
    return []


def _check_source_priority_excludes_extracted(extra: dict[str, Any]) -> list[Issue]:
    """Fires only when `paths.extracted_dir` is configured; compares
    `source_priority` against the template's OWN declared `extracted_dir`
    value, never a hardcoded path literal."""
    paths = extra.get("paths", {}) or {}
    extracted_dir = paths.get("extracted_dir")
    if not extracted_dir:
        return []
    project = extra.get("project", {}) or {}
    if any(extracted_dir in source for source in project.get("source_priority", [])):
        return [
            Issue(
                "error",
                f"`{extracted_dir}` no debe aparecer en source_priority como fuente activa.",
            )
        ]
    return []


def _check_preliminaries_pagination(template: Template) -> list[Issue]:
    """Fires only when `preliminaries` is declared. `body_pagination_start`
    is validated against the template's OWN declared `sections` (never a
    hardcoded section id); the roman-pagination sub-check runs only when
    `roman_pagination` itself is declared (spec: document-pipeline
    "Preliminaries checked only when declared")."""
    extra = template.model_extra or {}
    preliminaries = extra.get("preliminaries")
    if not preliminaries:
        return []
    issues: list[Issue] = []
    roman = preliminaries.get("roman_pagination")
    if roman and not roman.get("enabled"):
        issues.append(Issue("error", "La paginación romana de preliminares debe estar habilitada."))
    body_start = preliminaries.get("body_pagination_start") or {}
    section_id = body_start.get("section_id")
    declared_sections = {section.id for section in template.sections}
    if section_id and declared_sections and section_id not in declared_sections:
        issues.append(
            Issue(
                "error",
                f"`body_pagination_start.section_id` (`{section_id}`) no existe en `sections`.",
            )
        )
    return issues


def _check_margins_and_cover_policy(extra: dict[str, Any]) -> list[Issue]:
    """Fires only when `format.page_margins_cm.non_cover` is declared;
    validates the four margin keys hold numeric centimeter values, never a
    specific required value. `cover_policy` (if declared) only needs to be a
    string -- its meaning is document-type-specific, not enforced here (spec:
    document-pipeline "Margins checked for shape, not value")."""
    margin_contract = (extra.get("format", {}) or {}).get("page_margins_cm", {}) or {}
    non_cover_margins = margin_contract.get("non_cover")
    if not non_cover_margins:
        return []
    issues: list[Issue] = []
    bad_margins = [
        key
        for key in _MARGIN_KEYS
        # SUGGESTION-3 (fresh-context verify, PR1 fix batch): `bool` is an
        # `int` subclass in Python -- `isinstance(x, (int, float))` alone
        # would silently accept True/False as a "numeric" margin.
        if isinstance(non_cover_margins.get(key), bool) or not isinstance(non_cover_margins.get(key), (int, float))
    ]
    if bad_margins:
        issues.append(
            Issue(
                "error",
                "Los márgenes declarados deben ser valores numéricos en centímetros: "
                f"{', '.join(bad_margins)}.",
            )
        )
    cover_policy = margin_contract.get("cover_policy")
    if cover_policy is not None and not isinstance(cover_policy, str):
        issues.append(Issue("error", "`cover_policy` debe ser una cadena de texto."))
    return issues


def _check_section_contracts_content(template: Template) -> list[Issue]:
    issues: list[Issue] = []
    for section_id, contract in template.section_contracts.items():
        if not contract.required_content:
            issues.append(Issue("error", f"El contrato `{section_id}` no define contenido obligatorio."))
        # Duplicates the document-level APA gate above when both fire — this is
        # real legacy behavior (review_rules never deduplicates), preserve it.
        if contract.apa_required and not template.apa7.enabled:
            issues.append(Issue("error", f"El contrato `{section_id}` requiere APA pero APA 7 está deshabilitado."))
    return issues


def review_rules(
    template: Template, manifest_exists: bool, manifest_size: int, strict: bool = False
) -> ReviewResult:
    extra = template.model_extra or {}
    issues: list[Issue] = []
    issues.extend(_check_manifest_state(manifest_exists, manifest_size, strict))
    issues.extend(_check_missing_section_contracts(template))
    issues.extend(_check_extracted_dir_policy(extra))
    issues.extend(_check_source_priority_excludes_extracted(extra))
    issues.extend(_check_preliminaries_pagination(template))
    issues.extend(_check_margins_and_cover_policy(extra))
    issues.extend(_check_section_contracts_content(template))
    return ReviewResult(issues)


_DURATION_RE = re.compile(r"\b(\d{2,4})\s*horas\b", re.IGNORECASE)
_HEDGE_RE = re.compile(r"\b(contexto|prototipo|dependencia|externa|posible|planea|futur\w*)")

DEFAULT_CONTESTED_STACK_TERMS = ["Laravel", "Supabase", "bun.js", "MySQL", "GCP", "Firebase"]


def review_cross_consistency(
    template: Template,
    section_bodies: dict[str, str],
    strict: bool = False,
    contested_stack_terms: list[str] | None = None,
) -> ReviewResult:
    issues: list[Issue] = []
    severity = "error" if strict else "warning"
    terms = contested_stack_terms if contested_stack_terms is not None else DEFAULT_CONTESTED_STACK_TERMS

    references_body = section_bodies.get("referencias", "")
    references_pending = "pendiente" in clean_markdown_text(references_body).lower()

    citations: dict[str, str] = {}
    for section_id, body in section_bodies.items():
        if section_id == "referencias":
            continue
        for citation in extract_apa_citations(body):
            key = citation_author_key(citation)
            if key:
                citations.setdefault(key, citation)

    references = extract_reference_entries(references_body)
    reference_keys = {reference_author_key(entry) for entry in references}

    if not (references_pending and not strict):
        for key, citation in sorted(citations.items()):
            if not any(key in ref_key or ref_key in key for ref_key in reference_keys if ref_key):
                issues.append(
                    Issue(
                        severity,
                        f"Cita `{citation}` usada en el cuerpo no tiene referencia en REFERENCIAS BIBLIOGRÁFICAS.",
                        code="coherence.citation_without_global_reference",
                    )
                )
        for entry in references:
            ref_key = reference_author_key(entry)
            if ref_key and not any(ref_key in cite_key or cite_key in ref_key for cite_key in citations):
                issues.append(
                    Issue(
                        severity,
                        f"Referencia `{entry[:80]}` no está citada en ninguna sección del cuerpo.",
                        code="coherence.reference_without_global_citation",
                    )
                )

    hour_mentions: set[int] = set()
    for body in section_bodies.values():
        for match in _DURATION_RE.finditer(body):
            hour_mentions.add(int(match.group(1)))
    if len(hour_mentions) > 1:
        values = ", ".join(f"{value} horas" for value in sorted(hour_mentions))
        issues.append(
            Issue(
                severity,
                f"La duración de la estadía es inconsistente entre secciones: {values}.",
                code="coherence.duration_mismatch",
            )
        )

    for section_id, body in section_bodies.items():
        lowered = body.lower()
        section_pending = "pendiente" in lowered
        for term in terms:
            pattern = re.compile(rf"(?<![\w]){re.escape(term.lower())}(?![\w])")
            if pattern.search(lowered) and not section_pending and not _HEDGE_RE.search(lowered):
                issues.append(
                    Issue(
                        "warning",
                        f"`{section_id}` menciona tecnología en disputa `{term}` como definitiva "
                        "sin delimitarla ni marcar PENDIENTE.",
                        code="coherence.contested_stack_unqualified",
                    )
                )

    return ReviewResult(issues)
