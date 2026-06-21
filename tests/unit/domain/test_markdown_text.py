# tests/unit/domain/test_markdown_text.py
from docs.domain.markdown_text import (
    clean_markdown_text,
    dedupe_strings,
    extract_markdown_headings,
    keyword_set,
    matches_keywords,
    normalize_author_key,
    normalize_for_sort,
    normalize_heading,
    split_frontmatter,
    strip_frontmatter_and_markdown,
)


def test_split_frontmatter_parses_json_block():
    text = '---\n{"section_id": "intro"}\n---\nCuerpo.\n'
    metadata, body = split_frontmatter(text)
    assert metadata == {"section_id": "intro"}
    assert body == "Cuerpo.\n"


def test_split_frontmatter_no_block_returns_empty_metadata():
    text = "Solo cuerpo, sin frontmatter."
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_split_frontmatter_unclosed_block_returns_unchanged():
    text = "---\n{not closed"
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_split_frontmatter_invalid_json_returns_unchanged():
    text = "---\nnot json\n---\nCuerpo.\n"
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_clean_markdown_text_strips_markers_and_collapses_whitespace():
    text = "**bold** *italic* `code`   with   spaces"
    assert clean_markdown_text(text) == "bold italic code with spaces"


def test_clean_markdown_text_strips_backslashes():
    assert clean_markdown_text("a\\*b") == "a*b"


def test_clean_markdown_text_strips_leading_trailing_pipe_and_whitespace():
    assert clean_markdown_text("  | texto |  ") == "texto"


def test_strip_frontmatter_and_markdown_removes_fenced_code_inline_code_images_links_structure():
    text = (
        "---\n{}\n---\n"
        "# Título\n"
        "```\ncode block\n```\n"
        "Texto con `inline` y ![alt](img.png) y [link](http://x) y > cita y *en* _fasis_ y #tag y | tabla |\n"
    )
    result = strip_frontmatter_and_markdown(text)
    assert "code block" not in result
    assert "inline" in result
    assert "img.png" not in result
    assert "link" not in result
    assert "http://x" not in result
    assert "#" not in result
    assert "*" not in result
    assert "_" not in result
    assert ">" not in result
    assert "|" not in result


def test_extract_markdown_headings_all_levels_multiline():
    text = "# Uno\nTexto\n## Dos\n### Tres\nNo es heading"
    assert extract_markdown_headings(text) == ["Uno", "Dos", "Tres"]


def test_extract_markdown_headings_empty_when_none():
    assert extract_markdown_headings("Solo texto.") == []


def test_normalize_heading_transliterates_accents_and_uppercases():
    assert normalize_heading("Introducción") == "INTRODUCCION"
    assert normalize_heading("áéíóúñü") == "AEIOUNU"


def test_normalize_author_key_lowercases_and_collapses_non_alnum():
    assert normalize_author_key("García, M.") == "garcia m"


def test_normalize_for_sort_falls_back_to_lower_when_key_empty():
    assert normalize_for_sort("123") == "123"
    assert normalize_for_sort("García") == "garcia"


def test_dedupe_strings_normalizes_whitespace_and_dedupes():
    assert dedupe_strings(["a  b", "a b", "c"]) == ["a b", "c"]


def test_dedupe_strings_skips_blank_after_normalization():
    assert dedupe_strings(["   ", "x"]) == ["x"]


def test_dedupe_strings_empty_list_returns_empty_list():
    assert dedupe_strings([]) == []


def test_dedupe_strings_preserves_first_occurrence_order():
    assert dedupe_strings(["b", "a", "b", "a"]) == ["b", "a"]


def test_dedupe_strings_trims_leading_and_trailing_whitespace():
    assert dedupe_strings(["  x  "]) == ["x"]


def test_keyword_set_collects_tokens_of_length_4_or_more():
    assert keyword_set("Resultados del Proyecto") == {"resultados", "proyecto"}


def test_keyword_set_drops_short_tokens():
    assert "del" not in keyword_set("Resultados del Proyecto")


def test_keyword_set_merges_tokens_across_multiple_texts():
    result = keyword_set("Introducción", "alcance")
    assert {"introduccion", "alcance"} <= result


def test_keyword_set_returns_empty_set_for_empty_input():
    assert keyword_set("") == set()


def test_matches_keywords_empty_keywords_matches_everything():
    assert matches_keywords("cualquier texto", set()) is True


def test_matches_keywords_true_when_keyword_substring_present():
    assert matches_keywords("- El alcance del proyecto es claro", {"alcance"}) is True


def test_matches_keywords_false_when_no_keyword_present():
    assert matches_keywords("- Texto sin relación", {"alcance"}) is False
