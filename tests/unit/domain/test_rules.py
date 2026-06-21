from docs.domain.models.template import SectionContract, StrictPolicyBlock
from docs.domain.rules import requirement_present, review_apa7_text, review_section_contract


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
