from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from docs.domain.cover import CoverSpec, CoverVariant
from docs.infrastructure.docx.cover_compositor import compose_generated_cover


def _composed_cover(variant: CoverVariant) -> Document:
    document = Document()
    spec = CoverSpec(
        variant=variant,
        content={
            "institution": "Analytical Academy",
            "title": "Native Cover Report",
            "author": "Ada Lovelace",
        },
    )

    compose_generated_cover(document, spec, {})

    return document


def _paragraph(document: Document, text: str):
    return next(paragraph for paragraph in document.paragraphs if paragraph.text == text)


def test_declared_variants_compose_distinct_semantic_layouts():
    academic = _composed_cover(CoverVariant.ACADEMIC)
    institutional = _composed_cover(CoverVariant.INSTITUTIONAL)
    technical = _composed_cover(CoverVariant.TECHNICAL)
    minimal = _composed_cover(CoverVariant.MINIMAL)
    visual = _composed_cover(CoverVariant.VISUAL)
    custom = _composed_cover(CoverVariant.CUSTOM)

    assert len(academic.tables) == 2
    assert _paragraph(academic, "Native Cover Report").alignment == WD_ALIGN_PARAGRAPH.LEFT

    assert len(institutional.tables) == 1
    assert institutional.tables[0].cell(0, 0).text == "Analytical Academy"

    assert len(technical.tables) == 1
    assert "AUTHOR" in technical.tables[0].cell(0, 0).text
    assert _paragraph(technical, "Native Cover Report").alignment == WD_ALIGN_PARAGRAPH.LEFT

    assert len(minimal.tables) == 0
    assert _paragraph(minimal, "Ada Lovelace").alignment == WD_ALIGN_PARAGRAPH.RIGHT

    assert len(visual.tables) == 1
    assert "w:shd" in visual.tables[0]._tbl.xml

    assert len(custom.tables) == 0
    assert _paragraph(custom, "Native Cover Report").runs[0].font.size.pt == 24
    assert str(_paragraph(custom, "Native Cover Report").runs[0].font.color.rgb) == "404040"

