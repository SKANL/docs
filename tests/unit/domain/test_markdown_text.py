# tests/unit/domain/test_markdown_text.py
from docs.domain.markdown_text import (
    clean_markdown_text,
    extract_markdown_headings,
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
