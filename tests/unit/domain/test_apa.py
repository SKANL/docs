from docs.domain.apa import (
    citation_author_key,
    extract_apa_citations,
    extract_reference_entries,
    extract_references_block,
    reference_author_key,
)


def test_extract_apa_citations_parenthetical():
    text = "Esto se sostiene (García, 2020) en la literatura."
    assert extract_apa_citations(text) == {"García, 2020"}


def test_extract_apa_citations_parenthetical_with_letter_suffix_and_extra_text():
    text = "Ver (García, 2020a, p. 5)."
    assert extract_apa_citations(text) == {"García, 2020a, p. 5"}


def test_extract_apa_citations_narrative():
    text = "García (2020) sostiene que esto es así."
    assert extract_apa_citations(text) == {"García, 2020"}


def test_extract_apa_citations_narrative_with_et_al():
    text = "García et al. (2020) sostienen que esto es así."
    assert extract_apa_citations(text) == {"García et al., 2020"}


def test_extract_apa_citations_combines_both_forms():
    text = "García (2020) sostiene (Pérez, 2019) que..."
    assert extract_apa_citations(text) == {"García, 2020", "Pérez, 2019"}


def test_extract_apa_citations_empty_when_none():
    assert extract_apa_citations("Sin citas aquí.") == set()


def test_extract_references_block_returns_text_after_last_matching_heading():
    text = (
        "# Intro\nTexto\n"
        "# REFERENCIAS BIBLIOGRÁFICAS\n"
        "García, A. (2020). Título. Editorial.\n"
    )
    block = extract_references_block(text)
    assert "García, A. (2020)" in block
    assert "# Intro" not in block


def test_extract_references_block_case_insensitive_and_plain_referencias():
    text = "## referencias\nPérez, B. (2019). Otro título.\n"
    block = extract_references_block(text)
    assert "Pérez, B. (2019)" in block


def test_extract_references_block_empty_when_no_heading():
    assert extract_references_block("Sin sección de referencias.") == ""


def test_extract_references_block_uses_last_match_when_multiple():
    text = (
        "# REFERENCIAS\nPrimera, A. (2018).\n"
        "# REFERENCIAS\nSegunda, B. (2019).\n"
    )
    block = extract_references_block(text)
    assert "Primera" not in block
    assert "Segunda" in block


def test_extract_reference_entries_filters_headings_pending_and_non_dated_lines():
    text = (
        "# REFERENCIAS\n"
        "PENDIENTE: completar referencias.\n"
        "## Subtítulo ignorado\n"
        "García, A. (2020). Título. Editorial.\n"
        "Línea sin fecha que debe ignorarse.\n"
        "Pérez, B. (n.d.). Otro título.\n"
    )
    entries = extract_reference_entries(text)
    assert entries == [
        "García, A. (2020). Título. Editorial.",
        "Pérez, B. (n.d.). Otro título.",
    ]


def test_extract_reference_entries_empty_when_no_references_block():
    assert extract_reference_entries("Sin referencias.") == []


def test_citation_author_key_strips_et_al_and_ampersand():
    assert citation_author_key("García et al., 2020") == "garcia"
    assert citation_author_key("García & Pérez, 2020") == "garcia"
    assert citation_author_key("García y Pérez, 2020") == "garcia"


def test_citation_author_key_simple():
    assert citation_author_key("García, 2020") == "garcia"


def test_reference_author_key_takes_text_before_first_paren_and_comma():
    assert reference_author_key("García, A. (2020). Título.") == "garcia"


def test_reference_author_key_handles_no_comma_before_paren():
    assert reference_author_key("García (2020). Título.") == "garcia"
