"""Deterministic native DOCX cover compositor."""
from __future__ import annotations

from typing import Any

from docs.domain.cover import CoverSpec, CoverVariant, _cover_asset_path, resolve_cover_slots


def _clear_initial_paragraph(document: Any) -> None:
    if len(document.paragraphs) == 1 and not document.paragraphs[0].text and not document.tables:
        paragraph = document.paragraphs[0]
        paragraph._element.getparent().remove(paragraph._element)


def _set_page_options(document: Any, page: dict[str, Any], *, cm: Any, inches: Any) -> None:
    section = document.sections[0]
    if page.get("size") == "letter":
        section.page_width = inches(8.5)
        section.page_height = inches(11)
    elif page.get("size") == "A4":
        section.page_width = cm(21)
        section.page_height = cm(29.7)
    for attribute, key in (("top_margin", "top"), ("right_margin", "right"), ("bottom_margin", "bottom"), ("left_margin", "left")):
        value = page.get("margins_cm", {}).get(key)
        if isinstance(value, (int, float)):
            setattr(section, attribute, cm(float(value)))


def _set_page_background(document: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    background = document._element.find(qn("w:background"))
    if background is None:
        background = OxmlElement("w:background")
        document._element.insert(0, background)
    background.set(qn("w:color"), color)


def _valid_color(value: Any, fallback: str) -> str:
    color = str(value or fallback).lstrip("#").upper()
    return color if len(color) == 6 and all(char in "0123456789ABCDEF" for char in color) else fallback


def _add_text(
    document: Any,
    value: str,
    *,
    alignment: Any,
    color: str,
    size: float,
    bold: bool = False,
    before: float = 0,
    after: float = 12,
) -> Any:
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    paragraph.alignment = alignment
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)
    run = paragraph.add_run(value)
    run.font.name = "Times New Roman"
    run.font.bold = bold
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    return paragraph


def _shade(cell: Any, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    cell._tc.get_or_add_tcPr().append(shading)


def _add_banner(document: Any, value: str, color: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    _shade(cell, color)
    paragraph = cell.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run(value)
    run.font.name = "Times New Roman"
    run.font.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor.from_string("FFFFFF")


def _add_color_band(document: Any, color: str, height_pt: float) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    table = document.add_table(rows=1, cols=1)
    _shade(table.cell(0, 0), color)
    height = OxmlElement("w:trHeight")
    height.set(qn("w:val"), str(int(height_pt * 20)))
    height.set(qn("w:hRule"), "exact")
    table.rows[0]._tr.get_or_add_trPr().append(height)


def _compose_academic(
    document: Any,
    slots: dict[str, str],
    alignment: Any,
    title_color: str,
    body_color: str,
    accent: str,
    secondary_accent: str,
    title_size: float,
    top_space: float,
    decorated: bool = True,
) -> None:
    if decorated:
        _add_color_band(document, accent, 14)
        _add_color_band(document, secondary_accent, 4)
    if slots.get("eyebrow"):
        _add_text(document, slots["eyebrow"], alignment=alignment, color=accent, size=11, bold=True, before=top_space, after=18)
    for index, (name, value) in enumerate(slots.items()):
        if value and name != "eyebrow":
            _add_text(
                document,
                value,
                alignment=alignment,
                color=title_color if name == "title" else body_color,
                size=title_size if name == "title" else 12,
                bold=name in {"institution", "title"},
                before=top_space if index == 0 and not slots.get("eyebrow") else 0,
                after=32 if name == "title" else 12,
            )


def _compose_institutional(document: Any, slots: dict[str, str], alignment: Any, accent: str) -> None:
    institution = slots.get("institution")
    if institution:
        _add_banner(document, institution, accent)
    for name, value in slots.items():
        if value and name != "institution":
            _add_text(
                document,
                value,
                alignment=alignment,
                color=accent if name == "title" else "000000",
                size=22 if name == "title" else 12,
                bold=name == "title",
                before=36 if name == "title" else 0,
                after=28 if name == "title" else 12,
            )


def _compose_technical(document: Any, slots: dict[str, str], alignment: Any, accent: str) -> None:
    from docx.shared import RGBColor

    title = slots.get("title")
    if title:
        _add_text(document, "TECHNICAL REPORT", alignment=alignment, color=accent, size=11, bold=True, before=36, after=8)
        _add_text(document, title, alignment=alignment, color="000000", size=24, bold=True, after=24)
    metadata = [(name, value) for name, value in slots.items() if value and name != "title"]
    if metadata:
        table = document.add_table(rows=len(metadata), cols=2)
        table.style = "Table Grid"
        ordered = sorted(metadata, key=lambda item: (item[0] != "author", item[0]))
        for row, (name, value) in zip(table.rows, ordered, strict=True):
            row.cells[0].text = name.upper()
            row.cells[1].text = value
            _shade(row.cells[0], accent)
            for run in row.cells[0].paragraphs[0].runs:
                run.font.bold = True
                run.font.color.rgb = RGBColor.from_string("FFFFFF")


def _compose_minimal(document: Any, slots: dict[str, str], alignment: Any) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    for name, value in slots.items():
        if not value:
            continue
        position = WD_ALIGN_PARAGRAPH.RIGHT if name != "title" else alignment
        _add_text(
            document,
            value,
            alignment=position,
            color="000000",
            size=18 if name == "title" else 10,
            bold=name == "title",
            before=144 if name == "title" else 0,
            after=20 if name == "title" else 6,
        )


def _compose_visual(document: Any, slots: dict[str, str], alignment: Any, accent: str) -> None:
    _add_banner(document, "", accent)
    for name, value in slots.items():
        if value:
            _add_text(
                document,
                value,
                alignment=alignment,
                color=accent if name == "title" else "000000",
                size=28 if name == "title" else 12,
                bold=name == "title",
                before=48 if name == "title" else 0,
                after=28 if name == "title" else 12,
            )


def _add_cover_images(document: Any, spec: CoverSpec, config: dict[str, Any], *, inches: Any) -> None:
    """Embed declared cover images as editable DOCX relationships."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    for name in ("hero", "logo"):
        path = _cover_asset_path(spec.visual.get(name), config)
        if path is None or not path.is_file():
            continue
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        width = spec.layout.get(f"{name}_width_in", 6.25 if name == "hero" else 1.35)
        if type(width) not in {int, float} or float(width) <= 0:
            width = 6.25 if name == "hero" else 1.35
        paragraph.add_run().add_picture(str(path), width=inches(float(width)))


def compose_generated_cover(document: Any, spec: CoverSpec, config: dict[str, Any]) -> None:
    """Append one deterministic cover page using only python-docx primitives."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Inches

    _clear_initial_paragraph(document)
    slots = resolve_cover_slots(spec, config)
    variant = spec.variant
    alignment = WD_ALIGN_PARAGRAPH.LEFT if variant is CoverVariant.ACADEMIC else WD_ALIGN_PARAGRAPH.CENTER
    title_color = "000000"
    title_size = 24.0 if variant is CoverVariant.CUSTOM else 20.0
    layout = spec.layout
    if variant is CoverVariant.CUSTOM:
        alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
        }.get(str(layout.get("alignment", "center")).lower(), WD_ALIGN_PARAGRAPH.CENTER)
        title_size = float(layout.get("title_size_pt", title_size))
    accent = _valid_color(spec.visual.get("accent", spec.visual.get("accent_color")), "0F766E")
    secondary_accent = _valid_color(spec.visual.get("secondary_accent"), "D97706")
    title_color = _valid_color(spec.visual.get("title_color"), "0B1F33")
    body_color = _valid_color(spec.visual.get("body_color"), "334155")
    _set_page_background(document, _valid_color(spec.page.get("background"), "F4F7FA"))
    _set_page_options(document, spec.page, cm=Cm, inches=Inches)
    _add_cover_images(document, spec, config, inches=Inches)

    if variant is CoverVariant.INSTITUTIONAL:
        _compose_institutional(document, slots, alignment, accent)
    elif variant is CoverVariant.TECHNICAL:
        _compose_technical(document, slots, WD_ALIGN_PARAGRAPH.LEFT, accent)
    elif variant is CoverVariant.MINIMAL:
        _compose_minimal(document, slots, alignment)
    elif variant is CoverVariant.VISUAL:
        _compose_visual(document, slots, alignment, accent)
    else:
        _compose_academic(
            document,
            slots,
            alignment,
            _valid_color(spec.visual.get("title_color"), "404040") if variant is CoverVariant.CUSTOM else title_color,
            body_color,
            accent,
            secondary_accent,
            title_size,
            float(layout.get("top_space_pt", 96)),
            decorated=variant is not CoverVariant.CUSTOM,
        )
