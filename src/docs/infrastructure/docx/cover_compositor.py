"""Deterministic native DOCX cover compositor."""
from __future__ import annotations

from typing import Any

from docs.domain.cover import CoverSpec, CoverVariant, resolve_cover_slots

_ALIASED_VARIANTS = {
    CoverVariant.INSTITUTIONAL: CoverVariant.ACADEMIC,
    CoverVariant.TECHNICAL: CoverVariant.ACADEMIC,
    CoverVariant.MINIMAL: CoverVariant.ACADEMIC,
    CoverVariant.VISUAL: CoverVariant.ACADEMIC,
}


def _clear_initial_paragraph(document: Any) -> None:
    if len(document.paragraphs) == 1 and not document.paragraphs[0].text and not document.tables:
        paragraph = document.paragraphs[0]
        paragraph._element.getparent().remove(paragraph._element)


def compose_generated_cover(document: Any, spec: CoverSpec, config: dict[str, Any]) -> None:
    """Append one deterministic cover page using only python-docx primitives."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Inches, Pt, RGBColor

    _clear_initial_paragraph(document)
    slots = resolve_cover_slots(spec, config)
    variant = _ALIASED_VARIANTS.get(spec.variant, spec.variant)
    style: tuple[Any, str, float] = {
        CoverVariant.ACADEMIC: (WD_ALIGN_PARAGRAPH.CENTER, "000000", 20),
        CoverVariant.CUSTOM: (WD_ALIGN_PARAGRAPH.CENTER, "000000", 20),
    }[variant]
    alignment, title_color, title_size = style
    title_size = float(title_size)
    layout = spec.layout
    if variant is CoverVariant.CUSTOM:
        alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
        }.get(str(layout.get("alignment", "center")).lower(), WD_ALIGN_PARAGRAPH.CENTER)
        title_size = float(layout.get("title_size_pt", title_size))
    accent = str(spec.visual.get("accent_color", title_color)).lstrip("#").upper()
    if len(accent) == 6 and all(char in "0123456789ABCDEF" for char in accent):
        title_color = accent

    page = spec.page
    section = document.sections[0]
    if page.get("size") == "letter":
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
    elif page.get("size") == "A4":
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
    for attribute, key in (("top_margin", "top"), ("right_margin", "right"), ("bottom_margin", "bottom"), ("left_margin", "left")):
        value = page.get("margins_cm", {}).get(key)
        if isinstance(value, (int, float)):
            setattr(section, attribute, Cm(float(value)))

    for index, (name, value) in enumerate(slots.items()):
        if not value:
            continue
        paragraph = document.add_paragraph()
        paragraph.alignment = alignment
        paragraph.paragraph_format.space_after = Pt(12 if name != "title" else 28)
        if index == 0 and name != "title":
            paragraph.paragraph_format.space_before = Pt(float(layout.get("top_space_pt", 96)))
        run = paragraph.add_run(value)
        run.font.name = "Times New Roman"
        run.font.bold = name in {"institution", "title"}
        run.font.size = Pt(title_size if name == "title" else 12)
        run.font.color.rgb = RGBColor.from_string(title_color if name == "title" else "000000")
