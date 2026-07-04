# tests/unit/domain/test_section_rendering.py
from docs.domain.models.template import SectionContract
from docs.domain.section_rendering import (
    _extract_heading_block,
    _extract_table_value,
    _summarize_context,
    apply_keyword_bold,
    render_contract_scaffold,
    render_section_draft,
    render_toc_section,
)


class TestApplyKeywordBold:
    def test_no_terms_returns_markdown_unchanged(self):
        assert apply_keyword_bold("hello world", []) == "hello world"

    def test_bolds_matching_term_case_insensitively(self):
        assert apply_keyword_bold("the API is great", ["api"]) == "the **API** is great"

    def test_does_not_double_bold_inside_existing_bold_span(self):
        assert apply_keyword_bold("**API** docs", ["api"]) == "**API** docs"

    def test_longest_term_processed_first_but_overlapping_shorter_term_still_matches(self):
        # Verbatim legacy behavior: terms are sorted longest-first, but each term's
        # substitution runs as an independent regex pass over the (so-far-substituted)
        # string. Bold-span protection only guards markup that existed BEFORE this
        # function ran — newly-inserted ** markers from an earlier (longer) term in
        # the same call are not re-protected, so a later (shorter) overlapping term
        # can still match inside them. This is legacy's actual, verified behavior
        # (not a bug introduced by this port) — see plan Slice 8 Task 1 review note.
        result = apply_keyword_bold("REST API client", ["api", "REST API"])
        assert result == "**REST **API**** client"

    def test_non_overlapping_terms_of_different_lengths_both_bolded_correctly(self):
        result = apply_keyword_bold("alpha beta", ["beta", "alphabet"])
        assert result == "alpha **beta**"

    def test_word_boundary_respected(self):
        assert apply_keyword_bold("apiary", ["api"]) == "apiary"

    def test_empty_terms_in_list_are_skipped(self):
        assert apply_keyword_bold("hello world", ["", "world"]) == "hello **world**"

    def test_multiple_distinct_terms_all_bolded(self):
        result = apply_keyword_bold("alpha beta gamma", ["alpha", "gamma"])
        assert result == "**alpha** beta **gamma**"

    def test_term_preceded_by_at_sign_is_not_bolded(self):
        assert apply_keyword_bold("contact @api now", ["api"]) == "contact @api now"

    def test_term_followed_by_word_character_is_not_bolded(self):
        assert apply_keyword_bold("apis are great", ["api"]) == "apis are great"

    def test_existing_bold_span_with_multiple_words_is_protected(self):
        markdown = "**REST API** and api docs"
        result = apply_keyword_bold(markdown, ["api"])
        assert result == "**REST API** and **api** docs"

    def test_multiple_existing_bold_spans_all_protected(self):
        markdown = "**one** plain **two**"
        result = apply_keyword_bold(markdown, ["plain"])
        assert result == "**one** **plain** **two**"

    def test_repeated_term_occurrences_all_bolded(self):
        result = apply_keyword_bold("api api api", ["api"])
        assert result == "**api** **api** **api**"


class TestRenderTocSection:
    def test_renders_title_and_toc_marker(self):
        assert render_toc_section("Índice") == "# Índice\n\n[[TOC]]\n"


class TestSummarizeContext:
    def test_extracts_table_rows_as_bullets(self):
        context = {"topic": "| **Campo** | Información |\n| **Nombre** | Juan |\n"}
        assert "- Nombre: Juan" in _summarize_context(context)

    def test_skips_campo_header_row(self):
        context = {"topic": "| **Campo** | Información |\n"}
        assert _summarize_context(context) == []

    def test_prose_topic_without_pipe_yields_snippet_bullet(self):
        context = {"intro": "# Intro\n\nUna nota de prosa relevante."}
        lines = _summarize_context(context)
        assert any("Intro" in line and "prosa relevante" in line for line in lines)

    def test_prose_topic_without_heading_uses_dict_key_as_label(self):
        context = {"nota": "Texto de prosa simple sin encabezado."}
        lines = _summarize_context(context)
        assert any(line.startswith("- nota:") for line in lines)

    def test_prose_longer_than_200_chars_gets_ellipsis(self):
        prose = "x" * 250
        context = {"intro": f"# Intro\n\n{prose}"}
        lines = _summarize_context(context)
        assert any(line.endswith("…") for line in lines)

    def test_prose_shorter_than_200_chars_has_no_ellipsis(self):
        context = {"intro": "# Intro\n\nCorto."}
        lines = _summarize_context(context)
        assert not any(line.endswith("…") for line in lines)

    def test_topics_are_processed_in_sorted_key_order(self):
        context = {
            "b_topic": "| **Campo** | Información |\n| **B** | segundo |\n",
            "a_topic": "| **Campo** | Información |\n| **A** | primero |\n",
        }
        lines = _summarize_context(context)
        assert lines.index("- A: primero") < lines.index("- B: segundo")

    def test_table_row_with_empty_value_is_skipped(self):
        context = {"topic": "| **Nombre** |  |\n"}
        assert _summarize_context(context) == []

    def test_empty_context_returns_empty_list(self):
        assert _summarize_context({}) == []

    def test_text_with_pipe_does_not_also_produce_prose_bullet(self):
        context = {"topic": "| **Nombre** | Juan |\ntexto suelto con | pipe"}
        lines = _summarize_context(context)
        assert lines == ["- Nombre: Juan"]


class TestRenderContractScaffold:
    def test_includes_required_content_pendientes(self):
        contract = SectionContract(required_content=["alcance"])
        body = render_contract_scaffold("Resultados", contract, {})
        assert "PENDIENTE: documentar alcance" in body

    def test_includes_apa_pendiente_when_apa_required(self):
        body = render_contract_scaffold("Discusión", SectionContract(apa_required=True), {})
        assert "Fuentes APA 7" in body
        assert "PENDIENTE: agregar citas autor-fecha" in body

    def test_includes_context_section_when_context_present(self):
        context = {"topic": "| **Campo** | Información |\n| **Nombre** | Ana |\n"}
        body = render_contract_scaffold("Intro", SectionContract(), context)
        assert "## Contexto disponible" in body
        assert "- Nombre: Ana" in body

    def test_includes_references_list_pendiente_when_references_list_true(self):
        body = render_contract_scaffold("Referencias", SectionContract(references_list=True), {})
        assert "PENDIENTE: ordenar alfabéticamente" in body

    def test_omits_context_section_when_context_empty(self):
        body = render_contract_scaffold("Intro", SectionContract(), {})
        assert "## Contexto disponible" not in body

    def test_omits_pendientes_normativos_when_required_content_empty(self):
        body = render_contract_scaffold("Intro", SectionContract(), {})
        assert "## Pendientes normativos" not in body

    def test_omits_apa_section_when_apa_not_required(self):
        body = render_contract_scaffold("Intro", SectionContract(), {})
        assert "Fuentes APA 7" not in body

    def test_omits_references_list_pendiente_when_not_required(self):
        body = render_contract_scaffold("Intro", SectionContract(), {})
        assert "PENDIENTE: ordenar alfabéticamente" not in body

    def test_includes_title_and_disclaimer(self):
        body = render_contract_scaffold("Mi Sección", SectionContract(), {})
        assert body.startswith("# Mi Sección")
        assert "Borrador inicial generado por el arnés" in body

    def test_multiple_required_content_items_each_get_a_pendiente_line(self):
        contract = SectionContract(required_content=["alcance", "objetivo"])
        body = render_contract_scaffold("Resultados", contract, {})
        assert "PENDIENTE: documentar alcance" in body
        assert "PENDIENTE: documentar objetivo" in body

    def test_all_sections_present_together(self):
        contract = SectionContract(required_content=["alcance"], apa_required=True, references_list=True)
        context = {"topic": "| **Campo** | Información |\n| **Nombre** | Ana |\n"}
        body = render_contract_scaffold("Completa", contract, context)
        assert "## Contexto disponible" in body
        assert "## Pendientes normativos" in body
        assert "Fuentes APA 7" in body
        assert "PENDIENTE: ordenar alfabéticamente" in body


class TestRenderSectionDraft:
    def test_toc_contract_renders_toc_body(self):
        body = render_section_draft("toc", "Índice", SectionContract(toc=True), {}, [])
        assert "[[TOC]]" in body

    def test_non_toc_contract_renders_scaffold_and_applies_bold(self):
        body = render_section_draft("intro", "Introducción", SectionContract(), {}, ["alcance"])
        assert "# Introducción" in body

    def test_keyword_bold_terms_applied_to_scaffold_body(self):
        contract = SectionContract(required_content=["alcance"])
        body = render_section_draft("intro", "Introducción", contract, {}, ["alcance"])
        assert "**alcance**" in body

    def test_keyword_bold_terms_applied_to_toc_body(self):
        body = render_section_draft("toc", "Índice general", SectionContract(toc=True), {}, ["general"])
        assert "**general**" in body

    def test_no_keyword_bold_terms_leaves_body_unchanged_aside_from_terms(self):
        body = render_section_draft("toc", "Índice", SectionContract(toc=True), {}, [])
        assert body == "# Índice\n\n[[TOC]]\n"


class TestExtractTableValue:
    def test_extracts_value_for_field(self):
        markdown = "| **Nombre** | Juan |"
        assert _extract_table_value(markdown, "Nombre") == "Juan"

    def test_returns_empty_when_field_absent(self):
        assert _extract_table_value("| **Otro** | x |", "Nombre") == ""

    def test_extraction_is_case_insensitive(self):
        assert _extract_table_value("| **nombre** | Juan |", "Nombre") == "Juan"

    def test_extracted_value_is_cleaned_of_markdown_markers(self):
        assert _extract_table_value("| **Nombre** | **Juan** |", "Nombre") == "Juan"


class TestExtractHeadingBlock:
    def test_extracts_block_until_next_heading(self):
        markdown = "# Título\nlinea 1\nlinea 2\n# Otro\nignorada"
        assert _extract_heading_block(markdown, "Título") == "linea 1\nlinea 2"

    def test_returns_empty_when_heading_absent(self):
        assert _extract_heading_block("# Otro\ntexto", "Título") == ""

    def test_matches_bold_heading_variant(self):
        markdown = "# **Título**\nlinea 1\n# Otro"
        assert _extract_heading_block(markdown, "Título") == "linea 1"

    def test_capture_continues_until_end_of_document_when_no_further_heading(self):
        markdown = "# Título\nlinea 1\nlinea 2"
        assert _extract_heading_block(markdown, "Título") == "linea 1\nlinea 2"

    def test_matching_is_case_insensitive(self):
        markdown = "# título\nlinea 1\n# Otro"
        assert _extract_heading_block(markdown, "Título") == "linea 1"


class TestRenderContractScaffoldLegacyParity:
    def test_matches_legacy_render_contract_scaffold_byte_for_byte(self):
        # Transcribed line-by-line from tesina_harness.py:1342-1377's
        # render_contract_scaffold(config, section, context) for a synthetic
        # section exercising every optional block at once (context table row,
        # required_content PENDIENTEs, apa_required, references_list). This is
        # the parity proof Slice 17's design Goal 1 requires — it does not
        # exercise new code, it proves the already-shipped port is correct.
        contract = SectionContract(
            required_content=["alcance", "objetivo"],
            apa_required=True,
            references_list=True,
        )
        context = {"alumno": "| **Campo** | Información |\n| **Nombre** | Ana |\n"}

        body = render_contract_scaffold("Resultados", contract, context)

        expected = "\n".join(
            [
                "# Resultados",
                "",
                "_Borrador inicial generado por el arnés. Esta sección no debe "
                "considerarse lista hasta resolver todos los PENDIENTE con evidencia._",
                "",
                "## Contexto disponible",
                "",
                "- Nombre: Ana",
                "",
                "## Pendientes normativos",
                "",
                "- PENDIENTE: documentar alcance con evidencia del ledger, contexto o fuentes.",
                "- PENDIENTE: documentar objetivo con evidencia del ledger, contexto o fuentes.",
                "",
                "## Fuentes APA 7",
                "",
                "- PENDIENTE: agregar citas autor-fecha y referencias APA 7 realmente consultadas.",
                "",
                "PENDIENTE: ordenar alfabéticamente todas las fuentes citadas en el cuerpo conforme a APA 7.",
                "",
            ]
        )
        assert body == expected
