from __future__ import annotations

from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import safe_style_name


def test_safe_style_name_returns_preferred_when_already_available():
    document = Document()
    assert safe_style_name(document, "Heading 1") == "Heading 1"


def test_safe_style_name_maps_first_paragraph_to_no_spacing():
    document = Document()
    assert "First Paragraph" not in {s.name for s in document.styles}
    assert safe_style_name(document, "First Paragraph") == "No Spacing"


def test_safe_style_name_maps_compact_to_no_spacing():
    document = Document()
    assert safe_style_name(document, "Compact") == "No Spacing"


def test_safe_style_name_falls_back_to_normal_when_no_mapping_matches():
    document = Document()
    assert safe_style_name(document, "Some Unknown Style") == "Normal"


def test_safe_style_name_returns_none_when_neither_fallback_exists():
    class _FakeStyle:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeDocument:
        styles = [_FakeStyle("Custom Only")]

    assert safe_style_name(_FakeDocument(), "First Paragraph") is None


def test_safe_style_name_returns_none_for_none_preferred_style_without_fallback():
    class _FakeStyle:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeDocument:
        styles = [_FakeStyle("Custom Only")]

    assert safe_style_name(_FakeDocument(), None) is None
