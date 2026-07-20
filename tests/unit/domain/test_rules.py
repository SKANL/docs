import inspect

import pytest

from docs.domain import rules as rules_module
from docs.domain.models.template import SectionContract, StrictPolicyBlock
from docs.domain.rules import requirement_present, review_apa7_text, review_section_contract


def test_module_source_has_no_tesina_literal():
    assert "tesina" not in inspect.getsource(rules_module).lower()


def _policy(**overrides) -> StrictPolicyBlock:
    return StrictPolicyBlock(**overrides)


def test_requirement_present_uses_detect_candidates_when_provided():
    detect = {"metodología": ["enfoque cualitativo", "diseño de estudio"]}
    plain = "se utilizó un enfoque cualitativo para el análisis"
    assert requirement_present("metodología", plain, detect) is True


def test_requirement_present_false_when_detect_candidates_absent():
    detect = {"metodología": ["enfoque cualitativo"]}
    plain = "no se menciona nada relevante aquí"
    assert requirement_present("metodología", plain, detect) is False


def test_requirement_present_falls_back_to_requirement_words_when_no_detect():
    plain = "este texto menciona metodología explícitamente"
    assert requirement_present("metodología utilizada", plain, {}) is True


def test_requirement_present_false_when_no_match_and_no_detect():
    plain = "texto que no tiene relación alguna"
    assert requirement_present("metodología utilizada", plain, {}) is False


def test_requirement_present_false_against_the_harness_own_pendiente_scaffold_line():
    # CRITICAL-1 (verify-report-pr6.md): render_contract_scaffold's own
    # "PENDIENTE: documentar {item} con evidencia..." placeholder line
    # embeds the requirement's own words -- must NEVER count as "present".
    # Real scaffold output, not hand-typed text (the exact verifier repro).
    from docs.domain.markdown_text import clean_markdown_text
    from docs.domain.section_rendering import render_contract_scaffold

    contract = SectionContract(required_content=["objetivo del proyecto", "justificacion", "problema"])
    scaffold = render_contract_scaffold("Introducción", contract, context={})
    plain = clean_markdown_text(scaffold).lower()

    for requirement in contract.required_content:
        assert requirement_present(requirement, plain, {}) is False, requirement


def test_requirement_present_still_true_for_a_hand_authored_pendiente_note():
    # A human/AI-authored "PENDIENTE: <note>" (a different opening verb than
    # the harness's own three scaffold sentences) still counts as present --
    # e.g. the estadía "resultados importantes o PENDIENTE" detect override
    # relies on the bare word "pendiente" being an acceptable escape hatch.
    detect = {"resultados importantes o pendiente": ["resultado", "pendiente"]}
    plain = "pendiente: aún no hay resultados que reportar."
    assert requirement_present("resultados importantes o pendiente", plain, detect) is True


def test_scaffold_scrub_regex_covers_every_pendiente_sentence_the_scaffold_emits():
    # Drift guard: `_SCAFFOLD_PENDIENTE_RE` hardcodes the opening verbs of
    # `render_contract_scaffold`'s PENDIENTE sentences. A fourth sentence
    # template added there without updating the regex would silently reopen
    # CRITICAL-1 (a scaffolded section counting as already written). Driving
    # the real generator with every branch enabled keeps the two in lockstep:
    # any emitted `PENDIENTE:` sentence the regex fails to scrub fails here.
    from docs.domain.markdown_text import clean_markdown_text
    from docs.domain.rules import _SCAFFOLD_PENDIENTE_RE
    from docs.domain.section_rendering import render_contract_scaffold

    contract = SectionContract(
        required_content=["objetivo del proyecto"],
        apa_required=True,
        references_list=True,
    )
    plain = clean_markdown_text(
        render_contract_scaffold("Introducción", contract, context={})
    ).lower()

    assert "pendiente:" in plain  # the generator really did emit them
    assert "pendiente:" not in _SCAFFOLD_PENDIENTE_RE.sub(" ", plain)


def test_review_section_contract_no_issues_when_contract_satisfied():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Sección\n\nEl objetivo de este trabajo es claro y está bien definido con suficiente texto."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert issues == []


def test_review_section_contract_length_below_min_uses_strict_policy_severity():
    contract = SectionContract(length={"min_words": 1000})
    text = "# Sección\n\nTexto corto."
    issues = review_section_contract(text, "intro", contract, _policy(length_violations="error"), strict=False)
    assert len(issues) == 1
    assert issues[0].code == "contract.length_below_min"
    assert issues[0].severity == "error"
    assert "mínimo esperado: 1000" in issues[0].message


def test_review_section_contract_length_above_max():
    contract = SectionContract(length={"max_words": 2})
    text = "# Sección\n\nuno dos tres cuatro cinco"
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    codes = [i.code for i in issues]
    assert "contract.length_above_max" in codes


def test_review_section_contract_missing_required_uses_raw_strict_not_strict_policy():
    contract = SectionContract(required_content=["metodología"])
    text = "# Sección\n\nTexto sin relación alguna."
    # strict_policy says "warning" for everything, but `strict=True` should still
    # force the missing_required issue to "error" — this is the legacy asymmetry.
    issues = review_section_contract(
        text, "intro", contract, _policy(length_violations="warning"), strict=True
    )
    missing = next(i for i in issues if i.code == "contract.missing_required")
    assert missing.severity == "error"
    assert "metodología" in missing.message


def test_review_section_contract_missing_required_joins_multiple_terms():
    contract = SectionContract(required_content=["objetivo", "metodología"])
    text = "# Sección\n\nTexto sin relación alguna en absoluto."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    missing = next(i for i in issues if i.code == "contract.missing_required")
    assert "objetivo, metodología" in missing.message


def test_review_section_contract_evidence_required_flags_missing_evidence():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nNo hay nada que lo respalde aquí."
    issues = review_section_contract(text, "intro", contract, _policy(missing_evidence="error"), strict=False)
    issue = next(i for i in issues if i.code == "evidence.required")
    assert issue.severity == "error"
    assert "requiere evidencia o marcador PENDIENTE" in issue.message


def test_review_section_contract_evidence_required_satisfied_by_pendiente_marker():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nEsto está PENDIENTE de completar."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "evidence.required" for i in issues)


def test_review_section_contract_evidence_required_satisfied_by_evidence_word():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nSe adjunta evidencia suficiente sobre el tema."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "evidence.required" for i in issues)


def test_review_section_contract_apa_required_flags_missing_citations():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nTexto sin ninguna cita bibliográfica aquí."
    issues = review_section_contract(text, "intro", contract, _policy(apa_violations="error"), strict=False)
    issue = next(i for i in issues if i.code == "apa.required")
    assert issue.severity == "error"
    assert "requiere citas APA 7" in issue.message


def test_review_section_contract_apa_required_satisfied_by_citation():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nEsto se sostiene (García, 2020) en la literatura."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "apa.required" for i in issues)


def test_review_section_contract_apa_required_satisfied_by_pendiente():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nEsto está PENDIENTE de citar."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "apa.required" for i in issues)


def test_review_apa7_text_disabled_returns_no_issues():
    text = "Esto se sostiene (García, 2020) sin lista de referencias."
    issues = review_apa7_text(text, apa7_enabled=False, strict_policy=_policy())
    assert issues == []


def test_review_apa7_text_citations_without_references_flags_no_reference_list():
    text = "Esto se sostiene (García, 2020) sin lista de referencias."
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy(apa_violations="error"))
    codes = [i.code for i in issues]
    assert "apa.no_reference_list" in codes
    assert "apa.citation_without_reference" in codes
    assert all(i.severity == "error" for i in issues)


def test_review_apa7_text_references_without_citations_flags_reference_without_citation():
    text = (
        "Texto sin citas en el cuerpo.\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Título largo de un trabajo. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    codes = [i.code for i in issues]
    assert "apa.reference_without_citation" in codes


def test_review_apa7_text_matching_citation_and_reference_no_issues():
    text = (
        "Esto se sostiene (García, 2020) en la literatura.\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Un título cualquiera. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code in {"apa.citation_without_reference", "apa.reference_without_citation"} for i in issues)


def test_review_apa7_text_unmatched_citation_among_others_flags_only_that_one():
    text = (
        "Esto se sostiene (García, 2020) y también (Pérez, 2021).\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Un título cualquiera. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    unmatched = [i for i in issues if i.code == "apa.citation_without_reference"]
    assert len(unmatched) == 1
    assert "Pérez" in unmatched[0].message


def test_review_apa7_text_references_not_sorted():
    text = (
        "(Zeta, 2020) y (Alfa, 2019) se citan aquí.\n\n"
        "# REFERENCIAS\n"
        "Zeta, A. (2020). Título Z.\n"
        "Alfa, B. (2019). Título A.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert any(i.code == "apa.references_not_sorted" for i in issues)


def test_review_apa7_text_references_sorted_no_issue():
    text = (
        "(Alfa, 2019) y (Zeta, 2020) se citan aquí.\n\n"
        "# REFERENCIAS\n"
        "Alfa, B. (2019). Título A.\n"
        "Zeta, A. (2020). Título Z.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code == "apa.references_not_sorted" for i in issues)


def test_review_apa7_text_quote_without_locator():
    text = 'Dice textualmente "esto es una cita larga de más de veinte caracteres" sin nada más.'
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert any(i.code == "apa.quote_without_locator" for i in issues)


def test_review_apa7_text_quote_with_nearby_locator_no_issue():
    text = 'Dice textualmente "esto es una cita larga de más de veinte caracteres" (p. 5) según el autor.'
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code == "apa.quote_without_locator" for i in issues)


def test_review_apa7_text_no_citations_no_references_no_issues():
    issues = review_apa7_text("Texto neutro sin nada relevante.", apa7_enabled=True, strict_policy=_policy())
    assert issues == []


def test_review_apa7_text_references_list_skips_reference_without_citation():
    # A dedicated bibliography (references_list section) legitimately has
    # reference entries but NO in-text citations -- the per-section audit must
    # NOT flag apa.reference_without_citation. Cross-document resolution
    # (coherence.*) still validates citation<->reference reciprocity elsewhere.
    text = (
        "# REFERENCIAS\n"
        "Alfa, B. (2019). Un título largo cualquiera. Editorial.\n"
        "Beta, C. (2020). Otro título largo diferente. Editorial.\n"
        "Gamma, D. (2021). Un tercer título extenso. Editorial.\n"
    )
    issues = review_apa7_text(
        text, apa7_enabled=True, strict_policy=_policy(apa_violations="error"), is_references_list=True
    )
    assert not any(i.code == "apa.reference_without_citation" for i in issues)


def test_review_apa7_text_references_list_still_flags_unsorted():
    # The sort check must survive: a bibliography must still be alphabetized.
    text = (
        "# REFERENCIAS\n"
        "Zeta, A. (2020). Título Z largo cualquiera. Editorial.\n"
        "Alfa, B. (2019). Título A largo cualquiera. Editorial.\n"
    )
    issues = review_apa7_text(
        text, apa7_enabled=True, strict_policy=_policy(), is_references_list=True
    )
    assert any(i.code == "apa.references_not_sorted" for i in issues)


def test_review_apa7_text_global_bibliography_skips_no_reference_list():
    # A citing chapter (NOT a references_list section) whose references live in
    # a consolidated document-level bibliography legitimately has no local
    # reference list. Citation<->reference reciprocity is the DOCUMENT-level job
    # of review_cross_consistency, so the per-section audit must NOT flag
    # apa.no_reference_list nor apa.citation_without_reference here.
    text = (
        "# Capítulo II\n\n"
        "El marco teórico se apoya en (Martin, 2018) y (Beck, 2003) "
        "para justificar el enfoque adoptado."
    )
    issues = review_apa7_text(
        text,
        apa7_enabled=True,
        strict_policy=_policy(apa_violations="error"),
        is_references_list=False,
        global_reference_list=True,
    )
    codes = [i.code for i in issues]
    assert "apa.no_reference_list" not in codes
    assert "apa.citation_without_reference" not in codes


def test_review_apa7_text_no_global_bibliography_still_flags_no_reference_list():
    # Regression guard: without a consolidated bibliography, a citing section
    # with no local reference list STILL fails (old behavior preserved).
    text = (
        "# Capítulo II\n\n"
        "El marco teórico se apoya en (Martin, 2018) y (Beck, 2003) "
        "para justificar el enfoque adoptado."
    )
    issues = review_apa7_text(
        text,
        apa7_enabled=True,
        strict_policy=_policy(apa_violations="error"),
        is_references_list=False,
        global_reference_list=False,
    )
    assert any(i.code == "apa.no_reference_list" for i in issues)


def test_review_section_contract_apa_required_skipped_for_references_list():
    # A references_list section requires reference entries, not in-text
    # citations -- apa.required must NOT fire even under strict.
    contract = SectionContract(apa_required=True, references_list=True)
    text = (
        "# REFERENCIAS\n"
        "Alfa, B. (2019). Un título largo cualquiera. Editorial.\n"
    )
    issues = review_section_contract(text, "referencias", contract, _policy(apa_violations="error"), strict=True)
    assert not any(i.code == "apa.required" for i in issues)


def test_review_section_text_references_list_bibliography_clean_under_strict():
    # End-to-end via review_section_text: a valid bibliography section (3+
    # entries, no citations) yields ZERO apa.required and ZERO
    # apa.reference_without_citation under strict.
    contract = SectionContract(apa_required=True, references_list=True)
    text = (
        "# REFERENCIAS\n"
        "Alfa, B. (2019). Un título largo cualquiera. Editorial.\n"
        "Beta, C. (2020). Otro título largo diferente. Editorial.\n"
        "Gamma, D. (2021). Un tercer título extenso. Editorial.\n"
    )
    issues = _call(text, contract=contract, strict=True)
    assert not any(i.code == "apa.reference_without_citation" for i in issues)
    assert not any(i.code == "apa.required" for i in issues)


from docs.domain.models.template import Template
from docs.domain.normative import NormativeSettings
from docs.domain.rules import review_section_text


def test_normative_settings_is_a_frozen_dataclass_with_expected_defaults():
    settings = NormativeSettings(
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    assert settings.scope_term == ""
    assert settings.scope_focus == ""
    with pytest.raises(Exception):
        settings.scope_term = "changed"  # frozen dataclass raises FrozenInstanceError


def _template(**overrides) -> Template:
    return Template(type="x", title="X", **overrides)


def _call(text, contract=None, template=None, strict=False, **kwargs):
    defaults = dict(
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
        scope_term="",
        scope_focus="",
    )
    defaults.update(kwargs)
    return review_section_text(
        text,
        {},
        "intro",
        contract or SectionContract(),
        template or _template(),
        strict,
        normative=NormativeSettings(**defaults),
    )


def test_review_section_text_excluded_term_flags_error_unless_policy_file():
    text = "# Título\n\nEste texto contiene plagio detectado."
    issues = _call(text, excluded_terms={"plagio": "No se permite contenido plagiado."})
    issue = next(i for i in issues if i.code == "scope.excluded_section")
    assert issue.severity == "error"
    assert "Contiene apartado excluido: `plagio`. No se permite contenido plagiado." == issue.message


def test_review_section_text_excluded_term_skipped_for_policy_file():
    text = "# Título\n\nEste texto contiene plagio detectado."
    issues = _call(text, excluded_terms={"plagio": "x"}, is_policy_file=True)
    assert not any(i.code == "scope.excluded_section" for i in issues)


def test_review_section_text_first_person_pattern_flags_error():
    text = "# Título\n\nYo considero que esto es así."
    issues = _call(text, first_person_patterns=[r"\byo\b"])
    issue = next(i for i in issues if i.code == "voice.first_person")
    assert issue.severity == "error"
    assert "patrón `\\byo\\b`" in issue.message


def test_review_section_text_subjective_term_always_warning():
    text = "# Título\n\nEsto es excelente sin duda."
    issues = _call(text, subjective_terms=["excelente"])
    issue = next(i for i in issues if i.code == "voice.subjective_term")
    assert issue.severity == "warning"


def test_review_section_text_secret_pattern_checked_against_raw_text_case_insensitive():
    text = "# Título\n\nAPI_KEY=ABC123SECRET"
    issues = _call(text, secret_patterns=[r"api_key\s*="])
    issue = next(i for i in issues if i.code == "privacy.sensitive_data")
    assert issue.severity == "error"


def test_review_section_text_scope_undelimited_warning():
    text = "# Título\n\nSe usa azure en este proyecto."
    issues = _call(text, scope_term="azure", scope_focus="estadía tic")
    issue = next(i for i in issues if i.code == "scope.undelimited_ecosystem")
    assert issue.severity == "warning"


def test_review_section_text_scope_check_skipped_when_focus_present():
    text = "# Título\n\nSe usa azure en el contexto de la estadía tic."
    issues = _call(text, scope_term="azure", scope_focus="estadía tic")
    assert not any(i.code == "scope.undelimited_ecosystem" for i in issues)


def test_review_section_text_missing_title_flagged():
    text = "Texto sin encabezado markdown."
    issues = _call(text)
    assert any(i.code == "structure.missing_title" for i in issues)


def test_review_section_text_missing_title_skipped_for_policy_file():
    text = "Texto sin encabezado markdown."
    issues = _call(text, is_policy_file=True)
    assert not any(i.code == "structure.missing_title" for i in issues)


def test_review_section_text_dispatches_to_contract_review():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Título\n\nTexto sin relación alguna."
    issues = _call(text, contract=contract)
    assert any(i.code == "contract.missing_required" for i in issues)


def test_review_section_text_contract_dispatch_skipped_for_policy_file():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Título\n\nTexto sin relación alguna."
    issues = _call(text, contract=contract, is_policy_file=True)
    assert not any(i.code == "contract.missing_required" for i in issues)


def test_review_section_text_pending_marker_flagged_when_not_allowed():
    contract = SectionContract(pending_allowed_in_draft=False)
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text, contract=contract)
    issue = next(i for i in issues if i.code == "content.pending_not_allowed")
    assert issue.severity == "error"


def test_review_section_text_pending_marker_allowed_by_default():
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text)
    assert not any(i.code == "content.pending_not_allowed" for i in issues)


def test_review_section_text_pending_marker_skipped_for_policy_file():
    contract = SectionContract(pending_allowed_in_draft=False)
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text, contract=contract, is_policy_file=True)
    assert not any(i.code == "content.pending_not_allowed" for i in issues)


def test_review_section_text_dispatches_to_apa7_review():
    text = "# Título\n\nEsto se sostiene (García, 2020) sin lista de referencias."
    issues = _call(text)
    assert any(i.code == "apa.no_reference_list" for i in issues)


def test_review_section_text_apa7_disabled_via_template_skips_apa_checks():
    text = "# Título\n\nEsto se sostiene (García, 2020) sin lista de referencias."
    template = _template(apa7={"enabled": False})
    issues = _call(text, template=template)
    assert not any(i.code.startswith("apa.") for i in issues)


def test_review_section_text_citing_chapter_clean_with_consolidated_bibliography():
    # Wiring guard: a citing chapter (references_list=False) in a template that
    # owns a consolidated bibliography section (references_list=True) must NOT
    # emit the per-section apa.no_reference_list / apa.citation_without_reference
    # false positives; document-level review_cross_consistency owns that check.
    template = _template(
        section_contracts={
            "cap-2": SectionContract(apa_required=True, references_list=False),
            "referencias": SectionContract(apa_required=True, references_list=True),
        }
    )
    contract = SectionContract(apa_required=True, references_list=False)
    text = "# Capítulo II\n\nEl enfoque se apoya en (Martin, 2018) y (Beck, 2003)."
    issues = _call(text, contract=contract, template=template, strict=True)
    codes = [i.code for i in issues]
    assert "apa.no_reference_list" not in codes
    assert "apa.citation_without_reference" not in codes


def test_review_section_text_results_without_evidence_warning():
    text = "# Título\n\nLos resultados obtenidos fueron positivos."
    issues = _call(text)
    issue = next(i for i in issues if i.code == "evidence.results_without_evidence")
    assert issue.severity == "warning"


def test_review_section_text_results_with_evidence_word_no_warning():
    text = "# Título\n\nLos resultados obtenidos se respaldan con evidencia adjunta."
    issues = _call(text)
    assert not any(i.code == "evidence.results_without_evidence" for i in issues)


def test_review_section_text_results_with_pendiente_no_warning():
    text = "# Título\n\nLos resultados están PENDIENTE de evaluación."
    issues = _call(text)
    assert not any(i.code == "evidence.results_without_evidence" for i in issues)


from docs.domain.rules import _check_excluded_terms


def test_check_excluded_terms_flags_error_with_reason_when_not_policy_file():
    issues = _check_excluded_terms(
        "este texto contiene plagio detectado",
        is_policy_file=False,
        excluded_terms={"plagio": "No se permite contenido plagiado."},
    )
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "scope.excluded_section"
    assert issues[0].message == "Contiene apartado excluido: `plagio`. No se permite contenido plagiado."


def test_check_excluded_terms_skipped_for_policy_file():
    issues = _check_excluded_terms(
        "este texto contiene plagio detectado",
        is_policy_file=True,
        excluded_terms={"plagio": "x"},
    )
    assert issues == []


from docs.domain.rules import review_rules


def _generic_extra() -> dict:
    """Baseline for a document type that declares NONE of the optional policy
    blocks (`preliminaries`, `format.page_margins_cm`, `paths.extracted_dir`,
    margin `advisor_overrides`) — proves each converted check in Phase 3 stays
    silent (no issue, not a default pass) when its block is simply absent."""
    return {
        "paths": {},
        "project": {},
    }


def _estadia_extra() -> dict:
    """Renamed, value-for-value unchanged from the former single baseline
    builder — the full estadía-shaped policy baseline. Proves each converted
    check in Phase 3 still fires identically when its block IS present
    (characterization proof, Decision 10.4)."""
    return {
        "paths": {
            "extracted_dir_policy": "rules_traceability_only",
            "extracted_dir": "docs/extracted",
        },
        "project": {"source_priority": ["tesina/manual"]},
        "preliminaries": {
            "roman_pagination": {"enabled": True},
            "body_pagination_start": {"section_id": "introduccion"},
        },
        "format": {
            "page_margins_cm": {
                "cover_policy": "preserve_template",
                "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5},
            }
        },
        "advisor_overrides": [{"id": "margins-2-5cm-non-cover", "status": "active"}],
    }


def _estadia_template(**overrides) -> Template:
    return Template.model_validate({"type": "x", "title": "X", **_estadia_extra(), **overrides})


# --- Optional-Block Absence Semantics (spec: document-template) ---------
#
# These prove each converted check stays SILENT (no issue at all, not a
# default pass) when its optional policy block is simply absent from the
# template's declared data.

from docs.domain.rules import (
    _check_extracted_dir_policy,
    _check_margins_and_cover_policy,
    _check_preliminaries_pagination,
    _check_source_priority_excludes_extracted,
)


def _generic_template(**overrides) -> Template:
    return Template.model_validate({"type": "x", "title": "X", **_generic_extra(), **overrides})


def test_check_extracted_dir_policy_silent_when_extracted_dir_absent():
    assert _check_extracted_dir_policy(_generic_extra()) == []


def test_check_source_priority_excludes_extracted_silent_when_extracted_dir_absent():
    # SUGGESTION-1 (fresh-context verify, PR1 fix batch): symmetry with the
    # other 3 "stays silent when block absent" tests -- this check gates on
    # `paths.extracted_dir`, same as `_check_extracted_dir_policy` above.
    extra = _generic_extra()
    extra["project"] = {"source_priority": ["anything/at/all"]}
    assert _check_source_priority_excludes_extracted(extra) == []


def test_check_preliminaries_pagination_silent_when_preliminaries_absent():
    assert _check_preliminaries_pagination(_generic_template()) == []


def test_check_margins_and_cover_policy_silent_when_margins_absent():
    assert _check_margins_and_cover_policy(_generic_extra()) == []


# `_check_apa7_enabled` was DELETED (spec: document-pipeline "APA gate
# respected") -- `review_apa7_text`'s existing `apa7.enabled` no-op gate is
# sufficient; see `test_review_rules_apa7_disabled_is_not_forced_and_raises_no_issue`
# below for the review_rules-level proof.


def test_review_rules_all_valid_no_issues():
    result = review_rules(_estadia_template(), manifest_exists=True, manifest_size=10, strict=False)
    assert result.issues == []
    assert result.passed is True


def test_review_rules_manifest_missing_warning_in_draft():
    result = review_rules(_estadia_template(), manifest_exists=False, manifest_size=0, strict=False)
    issue = next(i for i in result.issues if "manual-rules.json" in i.message and "ejecuta" in i.message)
    assert issue.severity == "warning"
    assert issue.code == ""


def test_review_rules_manifest_missing_error_in_strict():
    result = review_rules(_estadia_template(), manifest_exists=False, manifest_size=0, strict=True)
    issue = next(i for i in result.issues if "manual-rules.json" in i.message and "ejecuta" in i.message)
    assert issue.severity == "error"


def test_review_rules_manifest_empty_always_error():
    result = review_rules(_estadia_template(), manifest_exists=True, manifest_size=0, strict=False)
    issue = next(i for i in result.issues if "está vacío" in i.message)
    assert issue.severity == "error"


def test_review_rules_missing_section_contracts():
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "sections": [{"id": "intro", "title": "Intro"}, {"id": "resumen", "title": "Resumen"}],
            "section_contracts": {"intro": {}},
            **_estadia_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    issue = next(i for i in result.issues if "Faltan contratos" in i.message)
    assert "resumen" in issue.message


def test_review_rules_extracted_dir_policy_missing_when_extracted_dir_configured():
    extra = _estadia_extra()
    extra["paths"]["extracted_dir_policy"] = ""
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("extracted_dir_policy" in i.message for i in result.issues)


def test_review_rules_extracted_dir_policy_any_declared_string_accepted():
    # No hardcoded expected value (spec: document-pipeline "Extracted-dir
    # policy checked only when configured") -- any declared, internally
    # consistent string passes; only a missing/empty declaration is an error.
    extra = _estadia_extra()
    extra["paths"]["extracted_dir_policy"] = "anything_else"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert not any("extracted_dir_policy" in i.message for i in result.issues)


def test_review_rules_docs_extracted_in_source_priority():
    extra = _estadia_extra()
    extra["project"]["source_priority"] = ["docs/extracted/foo"]
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("source_priority" in i.message for i in result.issues)


def test_review_rules_apa7_disabled_is_not_forced_and_raises_no_issue():
    # spec: document-pipeline "APA gate respected" -- apa7.enabled=False must
    # not be forced true; review_apa7_text's own no-op gate is sufficient.
    template = Template.model_validate({"type": "x", "title": "X", "apa7": {"enabled": False}, **_estadia_extra()})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert not any(i.message == "APA 7 debe estar habilitado." for i in result.issues)
    assert result.passed is True


def test_review_rules_roman_pagination_disabled():
    extra = _estadia_extra()
    extra["preliminaries"]["roman_pagination"]["enabled"] = False
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("paginación romana" in i.message for i in result.issues)


def test_review_rules_body_pagination_start_section_not_declared():
    # No hardcoded "introduccion" literal (spec: document-pipeline
    # "Preliminaries checked only when declared") -- the check compares
    # against the template's OWN declared `sections`, so any undeclared
    # section id is rejected, not just a non-"introduccion" one.
    extra = _estadia_extra()
    extra["preliminaries"]["body_pagination_start"]["section_id"] = "no-declarada"
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "sections": [{"id": "introduccion", "title": "Introducción"}],
            **extra,
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("no existe en" in i.message for i in result.issues)


def test_review_rules_body_pagination_start_any_declared_section_accepted():
    extra = _estadia_extra()
    extra["preliminaries"]["body_pagination_start"]["section_id"] = "resumen"
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "sections": [{"id": "resumen", "title": "Resumen"}],
            **extra,
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert not any("no existe en" in i.message for i in result.issues)


def test_review_rules_cover_policy_must_be_a_string_when_declared():
    extra = _estadia_extra()
    extra["format"]["page_margins_cm"]["cover_policy"] = 123
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("`cover_policy`" in i.message for i in result.issues)


def test_review_rules_cover_policy_any_declared_string_accepted():
    # No hardcoded "preserve_template" literal (spec: document-pipeline
    # "Margins checked for shape, not value").
    extra = _estadia_extra()
    extra["format"]["page_margins_cm"]["cover_policy"] = "custom_layout"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert not any("`cover_policy`" in i.message for i in result.issues)


def test_review_rules_bad_margins_non_numeric_value_flagged():
    extra = _estadia_extra()
    extra["format"]["page_margins_cm"]["non_cover"]["top"] = "not-a-number"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("centímetros" in i.message for i in result.issues)


def test_review_rules_margins_any_numeric_value_accepted():
    # No hardcoded 2.5cm literal (spec: document-pipeline "Margins checked
    # for shape, not value") -- any numeric value passes.
    extra = _estadia_extra()
    extra["format"]["page_margins_cm"]["non_cover"]["top"] = 3.0
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert result.issues == []


def test_review_rules_bad_margins_bool_value_rejected():
    # SUGGESTION-3 (fresh-context verify, PR1 fix batch): `bool` is a Python
    # `int` subclass, so `isinstance(value, (int, float))` alone would
    # silently accept `True`/`False` as a "numeric" margin -- must be
    # rejected explicitly, since a boolean is never a valid centimeter value.
    extra = _estadia_extra()
    extra["format"]["page_margins_cm"]["non_cover"]["top"] = True
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("centímetros" in i.message for i in result.issues)


def test_review_rules_contract_without_required_content():
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "section_contracts": {"intro": {"required_content": []}},
            **_estadia_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("no define contenido obligatorio" in i.message for i in result.issues)


def test_review_rules_contract_apa_required_but_apa7_disabled_flags_contract_level_only():
    # `_check_apa7_enabled` was DELETED (spec: "APA gate respected") -- only
    # the section-contract-level check fires now, no document-level duplicate.
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "apa7": {"enabled": False},
            "section_contracts": {"intro": {"required_content": ["x"], "apa_required": True}},
            **_estadia_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    document_level = [i for i in result.issues if i.message == "APA 7 debe estar habilitado."]
    contract_level = [i for i in result.issues if "requiere APA pero APA 7 está deshabilitado" in i.message]
    assert document_level == []
    assert len(contract_level) == 1


def test_review_rules_all_issues_have_empty_code():
    result = review_rules(_estadia_template(), manifest_exists=False, manifest_size=0, strict=True)
    assert all(i.code == "" for i in result.issues)


from docs.domain.rules import review_cross_consistency


def test_review_cross_consistency_citation_without_global_reference():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nOtroAutor, B. (2019). Título.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.citation_without_global_reference")
    assert issue.severity == "warning"
    assert "García, 2020" in issue.message


def test_review_cross_consistency_reference_without_global_citation():
    bodies = {
        "introduccion": "Texto sin ninguna cita.",
        "referencias": "# REFERENCIAS\nGarcía, A. (2020). Un título largo cualquiera. Editorial.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.reference_without_global_citation")
    assert "García" in issue.message


def test_review_cross_consistency_matching_citation_and_reference_no_issue():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nGarcía, A. (2020). Un título largo cualquiera. Editorial.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(
        i.code in {"coherence.citation_without_global_reference", "coherence.reference_without_global_citation"}
        for i in result.issues
    )


def test_review_cross_consistency_referencias_section_itself_excluded_from_citation_pool():
    bodies = {
        "referencias": "(EsteAutor, 2020) # REFERENCIAS\nOtroAutor, B. (2019). Título.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    # "EsteAutor" citation lives only inside the referencias body, which is excluded
    # from the citation pool entirely -- so no citation-side issue should appear for it.
    assert not any("EsteAutor" in i.message for i in result.issues)


def test_review_cross_consistency_reciprocity_skipped_when_references_pending_and_not_strict():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nPENDIENTE de completar.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code.startswith("coherence.citation_without") for i in result.issues)
    assert not any(i.code.startswith("coherence.reference_without") for i in result.issues)


def test_review_cross_consistency_reciprocity_not_skipped_when_strict_even_if_pending():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nPENDIENTE de completar.",
    }
    result = review_cross_consistency(_template(), bodies, strict=True)
    assert any(i.code == "coherence.citation_without_global_reference" for i in result.issues)


def test_review_cross_consistency_duration_mismatch():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 200 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.duration_mismatch")
    assert "160 horas" in issue.message and "200 horas" in issue.message
    assert issue.severity == "warning"


def test_review_cross_consistency_duration_consistent_no_issue():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 160 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.duration_mismatch" for i in result.issues)


def test_review_cross_consistency_duration_mismatch_severity_tracks_strict():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 200 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=True)
    issue = next(i for i in result.issues if i.code == "coherence.duration_mismatch")
    assert issue.severity == "error"


def test_review_cross_consistency_contested_stack_term_unqualified():
    bodies = {"infraestructura": "El sistema usa MySQL como base de datos definitiva."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.contested_stack_unqualified")
    assert issue.severity == "warning"
    assert "MySQL" in issue.message
    assert "infraestructura" in issue.message


def test_review_cross_consistency_contested_stack_term_hedged_no_issue():
    bodies = {"infraestructura": "El sistema usa MySQL como posible dependencia externa en el prototipo."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.contested_stack_unqualified" for i in result.issues)


def test_review_cross_consistency_contested_stack_term_pendiente_no_issue():
    bodies = {"infraestructura": "El uso de MySQL está PENDIENTE de definición."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.contested_stack_unqualified" for i in result.issues)


def test_review_cross_consistency_contested_stack_terms_overridable():
    bodies = {"infraestructura": "El sistema usa Redis como base definitiva."}
    result = review_cross_consistency(_template(), bodies, strict=False, contested_stack_terms=["Redis"])
    assert any(i.code == "coherence.contested_stack_unqualified" and "Redis" in i.message for i in result.issues)


def test_review_cross_consistency_no_issues_for_empty_bodies():
    result = review_cross_consistency(_template(), {}, strict=False)
    assert result.issues == []
