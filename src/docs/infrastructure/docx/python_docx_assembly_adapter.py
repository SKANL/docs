from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from defusedxml.ElementTree import parse as safe_parse

from docs.domain.cover import CoverMode, resolve_cover_spec
from docs.domain.docx_structure import resolve_part_text, sections_index, structure_parts
from docs.domain.markdown_text import normalize_heading
from docs.domain.process_policy import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS
from docs.infrastructure.docx.cover_compositor import compose_generated_cover
from docs.infrastructure.docx.deterministic_zip import normalize_docx_zip_timestamps
from docs.infrastructure.docx.python_docx_audit_adapter import paragraph_has_numbering
from docs.infrastructure.tools.resolution import resolve_executable

# A figure/table caption line ("Figura 12. ...", "Tabla 5. ...", "Gráfico 3. ...").
# Centered at assembly like the image it labels (academic layout), never
# first-line-indented as body text. Matches the leading token only.
_CAPTION_RE = re.compile(r"^(Figura|Tabla|Gr[aá]fico|Gr[aá]fica)\s+\d+\.", re.IGNORECASE)


@dataclass(frozen=True)
class ThemeColors:
    navy: str = "000000"
    teal: str = "000000"
    warm_accent: str = "000000"
    soft_background: str = "FFFFFF"
    heading_1: str = "000000"
    heading_2: str = "000000"
    heading_3: str = "000000"


@dataclass(frozen=True)
class ThemeTypography:
    body_font: str = "Times New Roman"
    body_size_pt: float = 12
    heading_font: str = "Times New Roman"
    heading_1_size_pt: float = 12
    heading_2_size_pt: float = 12
    heading_3_size_pt: float = 12


@dataclass(frozen=True)
class ThemeSpacing:
    body_line_spacing: float = 1.5
    body_after_pt: float = 18
    heading_1_before_pt: float = 0
    heading_1_after_pt: float = 18
    heading_2_before_pt: float = 0
    heading_2_after_pt: float = 18
    heading_3_before_pt: float = 0
    heading_3_after_pt: float = 18


@dataclass(frozen=True)
class ThemeHeader:
    title: str = ""
    accent_color: str = "navy"


@dataclass(frozen=True)
class ThemeFooter:
    font_size_pt: float = 12
    color: str = "navy"


@dataclass(frozen=True)
class ThemeCaptions:
    color: str = "navy"


@dataclass(frozen=True)
class VisualTheme:
    colors: ThemeColors = ThemeColors()
    typography: ThemeTypography = ThemeTypography()
    spacing: ThemeSpacing = ThemeSpacing()
    header: ThemeHeader = ThemeHeader()
    footer: ThemeFooter = ThemeFooter()
    captions: ThemeCaptions = ThemeCaptions()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _hex_color(value: Any, default: str) -> str:
    candidate = str(value or default).lstrip("#").upper()
    return candidate if re.fullmatch(r"[0-9A-F]{6}", candidate) else default


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def resolve_visual_theme(config: dict[str, Any]) -> VisualTheme:
    """Resolve the optional document visual theme while retaining current defaults."""
    raw = _mapping(_mapping(config.get("format")).get("visual_theme"))
    colors = _mapping(raw.get("colors"))
    typography = _mapping(raw.get("typography"))
    spacing = _mapping(raw.get("spacing"))
    header = _mapping(raw.get("header"))
    footer = _mapping(raw.get("footer"))
    captions = _mapping(raw.get("captions"))
    defaults = ThemeColors()
    navy = _hex_color(colors.get("navy"), defaults.navy)
    teal = _hex_color(colors.get("teal"), defaults.teal)
    return VisualTheme(
        colors=ThemeColors(
            navy=navy,
            teal=teal,
            warm_accent=_hex_color(colors.get("warm_accent"), defaults.warm_accent),
            soft_background=_hex_color(colors.get("soft_background"), defaults.soft_background),
            heading_1=_hex_color(colors.get("heading_1"), navy),
            heading_2=_hex_color(colors.get("heading_2"), navy),
            heading_3=_hex_color(colors.get("heading_3"), teal),
        ),
        typography=ThemeTypography(
            body_font=str(typography.get("body_font") or ThemeTypography.body_font),
            body_size_pt=_number(typography.get("body_size_pt"), ThemeTypography.body_size_pt),
            heading_font=str(typography.get("heading_font") or ThemeTypography.heading_font),
            heading_1_size_pt=_number(typography.get("heading_1_size_pt"), ThemeTypography.heading_1_size_pt),
            heading_2_size_pt=_number(typography.get("heading_2_size_pt"), ThemeTypography.heading_2_size_pt),
            heading_3_size_pt=_number(typography.get("heading_3_size_pt"), ThemeTypography.heading_3_size_pt),
        ),
        spacing=ThemeSpacing(**{field: _number(spacing.get(field), getattr(ThemeSpacing(), field)) for field in ThemeSpacing.__dataclass_fields__}),
        header=ThemeHeader(title=str(header.get("title") or ""), accent_color=str(header.get("accent_color") or "navy")),
        footer=ThemeFooter(font_size_pt=_number(footer.get("font_size_pt"), ThemeFooter.font_size_pt), color=str(footer.get("color") or "navy")),
        captions=ThemeCaptions(color=str(captions.get("color") or "navy")),
    )


def has_visual_theme(config: dict[str, Any]) -> bool:
    return isinstance(_mapping(config.get("format")).get("visual_theme"), dict)


def _theme_color(theme: VisualTheme, name: str) -> str:
    return getattr(theme.colors, name, theme.colors.navy)


def _parse_part(path: Path) -> tuple[ET.ElementTree, ET.Element]:
    """Parse one OOXML part, returning its tree and a non-optional root.

    `safe_parse` (defusedxml, Design Decision 5.1) always yields a tree with
    a root; typeshed still types `ElementTree.getroot()` as optional because
    an `ElementTree` CAN be constructed empty. Narrowing once here keeps the
    four part-rewriting call sites free of a guard that cannot fire, instead
    of repeating the same `getroot()` pair at each of them.
    """
    tree = safe_parse(path)
    root = tree.getroot()
    if root is None:  # pragma: no cover - defusedxml never yields a rootless tree
        raise ValueError(f"La parte XML no tiene elemento raíz: {path}")
    return tree, root


def resolve_pandoc_executable(paths: dict[str, Any]) -> str | None:
    """Find pandoc. No well-known locations: its installer DOES set PATH, and
    nothing observed says otherwise -- inventing paths would be superstition."""
    return resolve_executable(paths, names=("pandoc",), config_prefix="pandoc")


def _style_is_usable(document: Any, name: str | None) -> bool:
    """Whether `add_paragraph(style=name)` will actually work on `document`.

    Listing and addressing are different questions. Iterating
    `document.styles` can yield a name that `document.styles[name]` cannot
    resolve, and which pandoc version produced the base document decides
    whether that happens: 12 assembly tests passed on pandoc 3.10 and died on
    3.1.3 with `KeyError: "no style with name 'Heading 1'"` -- raised from
    inside `add_paragraph`, after this function had approved the name.

    Asking the document to hand the style over is the only probe that answers
    the question the caller is really asking.
    """
    if not name:
        return False
    try:
        document.styles[name]
    except (KeyError, AttributeError, TypeError):
        return False
    return True


def safe_style_name(document: Any, preferred_style: str | None) -> str | None:
    if _style_is_usable(document, preferred_style):
        return preferred_style

    pandoc_style_map = {
        "First Paragraph": "No Spacing",
        "Body Text": "No Spacing",
        "Compact": "No Spacing",
    }
    mapped = pandoc_style_map.get(preferred_style or "")
    if _style_is_usable(document, mapped):
        return mapped
    for fallback in ("Normal", "No Spacing"):
        if _style_is_usable(document, fallback):
            return fallback
    return None


def set_bullet_numbering(paragraph: Any, num_id: int = 42) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        num_pr = OxmlElement("w:numPr")
        p_pr.append(num_pr)
    ilvl = num_pr.find(qn("w:ilvl"))
    if ilvl is None:
        ilvl = OxmlElement("w:ilvl")
        num_pr.append(ilvl)
    ilvl.set(qn("w:val"), "0")
    num_id_el = num_pr.find(qn("w:numId"))
    if num_id_el is None:
        num_id_el = OxmlElement("w:numId")
        num_pr.append(num_id_el)
    num_id_el.set(qn("w:val"), str(num_id))


def configure_unnumbered_section(section: Any, config: dict[str, Any]) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    apply_header_theme(section.header, resolve_visual_theme(config))


def configure_numbered_body_section(section: Any, config: dict[str, Any]) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    theme = resolve_visual_theme(config)
    apply_header_theme(section.header, theme)
    add_page_number_footer(section.footer, theme if has_visual_theme(config) else None)
    set_section_page_number_start(section, 1, "decimal")


def configure_roman_preliminary_section(section: Any, config: dict[str, Any], start: int = 2) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    theme = resolve_visual_theme(config)
    apply_header_theme(section.header, theme)
    add_page_number_footer(section.footer, theme if has_visual_theme(config) else None)
    set_section_page_number_start(section, start, "lowerRoman")


def apply_non_cover_section_layout(section: Any, config: dict[str, Any]) -> None:
    from docx.shared import Cm, Inches

    if config.get("format", {}).get("page_size") == "letter":
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)

    margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
    for attr, key in [
        ("top_margin", "top"),
        ("right_margin", "right"),
        ("bottom_margin", "bottom"),
        ("left_margin", "left"),
    ]:
        value = margins.get(key)
        if isinstance(value, (int, float)):
            setattr(section, attr, Cm(float(value)))


def apply_header_theme(header: Any, theme: VisualTheme) -> None:
    """Render an optional title-only header without changing current documents."""
    if not theme.header.title:
        return
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    paragraph = header.paragraphs[-1] if header.paragraphs else header.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_after = Pt(3)
    p_pr = paragraph._p.get_or_add_pPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), theme.colors.soft_background)
    p_pr.append(shading)
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:color"), _theme_color(theme, theme.header.accent_color))
    border.append(bottom)
    p_pr.append(border)
    run = paragraph.add_run(theme.header.title)
    run.font.name = theme.typography.heading_font
    run.font.size = Pt(8)
    color = _theme_color(theme, theme.header.accent_color)
    run.font.color.rgb = RGBColor.from_string(color)


def add_page_number_footer(footer: Any, theme: VisualTheme | None = None) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    paragraph = footer.paragraphs[-1] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    if theme is None:
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
    else:
        run.font.name = theme.typography.body_font
        run.font.size = Pt(theme.footer.font_size_pt)
        run.font.color.rgb = RGBColor.from_string(_theme_color(theme, theme.footer.color))

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)


def set_section_page_number_start(section: Any, start: int, fmt: str | None = None) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sect_pr = section._sectPr
    pg_num_type = sect_pr.find(qn("w:pgNumType"))
    if pg_num_type is None:
        pg_num_type = OxmlElement("w:pgNumType")
        sect_pr.append(pg_num_type)
    pg_num_type.set(qn("w:start"), str(start))
    if fmt:
        pg_num_type.set(qn("w:fmt"), fmt)


def clear_story_part(part: Any) -> None:
    element = part._element
    for child in list(element):
        element.remove(child)
    part.add_paragraph()


def ensure_bullet_numbering_part(docx_path: Path, num_id: int = 42) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("w", namespace)
    ET.register_namespace("rel", rel_namespace)
    ET.register_namespace("ct", content_namespace)
    with tempfile.TemporaryDirectory(prefix="docs_docx_numbering_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        document_xml = (tmp_path / "word" / "document.xml").read_text(encoding="utf-8")
        if f'w:numId w:val="{num_id}"' not in document_xml:
            return

        numbering_path = tmp_path / "word" / "numbering.xml"
        if numbering_path.exists():
            numbering_tree, numbering_root = _parse_part(numbering_path)
        else:
            numbering_path.parent.mkdir(parents=True, exist_ok=True)
            numbering_root = ET.Element(f"{{{namespace}}}numbering")
            numbering_tree = ET.ElementTree(numbering_root)

        # `is None`, never truthiness: `Element.__bool__` means "has
        # children" (deprecated in 3.12, an error later), so a present-but-
        # childless `<w:num>` read as absent and got a duplicate definition.
        if numbering_root.find(f".//{{{namespace}}}num[@{{{namespace}}}numId='{num_id}']") is None:
            abstract = ET.SubElement(numbering_root, f"{{{namespace}}}abstractNum", {f"{{{namespace}}}abstractNumId": str(num_id)})
            ET.SubElement(abstract, f"{{{namespace}}}multiLevelType", {f"{{{namespace}}}val": "hybridMultilevel"})
            lvl = ET.SubElement(abstract, f"{{{namespace}}}lvl", {f"{{{namespace}}}ilvl": "0"})
            ET.SubElement(lvl, f"{{{namespace}}}start", {f"{{{namespace}}}val": "1"})
            ET.SubElement(lvl, f"{{{namespace}}}numFmt", {f"{{{namespace}}}val": "bullet"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlText", {f"{{{namespace}}}val": "•"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlJc", {f"{{{namespace}}}val": "left"})
            p_pr = ET.SubElement(lvl, f"{{{namespace}}}pPr")
            tabs = ET.SubElement(p_pr, f"{{{namespace}}}tabs")
            ET.SubElement(tabs, f"{{{namespace}}}tab", {f"{{{namespace}}}val": "num", f"{{{namespace}}}pos": "720"})
            ET.SubElement(p_pr, f"{{{namespace}}}ind", {f"{{{namespace}}}left": "720", f"{{{namespace}}}hanging": "360"})
            r_pr = ET.SubElement(lvl, f"{{{namespace}}}rPr")
            ET.SubElement(r_pr, f"{{{namespace}}}rFonts", {f"{{{namespace}}}ascii": "Symbol", f"{{{namespace}}}hAnsi": "Symbol"})
            ET.SubElement(r_pr, f"{{{namespace}}}sz", {f"{{{namespace}}}val": "24"})
            num = ET.SubElement(numbering_root, f"{{{namespace}}}num", {f"{{{namespace}}}numId": str(num_id)})
            ET.SubElement(num, f"{{{namespace}}}abstractNumId", {f"{{{namespace}}}val": str(num_id)})
        numbering_tree.write(numbering_path, xml_declaration=True, encoding="UTF-8")

        rels_path = tmp_path / "word" / "_rels" / "document.xml.rels"
        rels_tree, rels_root = _parse_part(rels_path)
        numbering_rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        if not any(rel.get("Type") == numbering_rel_type for rel in rels_root):
            existing_ids = [int(match.group(1)) for rel in rels_root for match in [re.match(r"rId(\d+)$", rel.get("Id", ""))] if match]
            next_id = max(existing_ids or [0]) + 1
            ET.SubElement(rels_root, f"{{{rel_namespace}}}Relationship", {"Id": f"rId{next_id}", "Type": numbering_rel_type, "Target": "numbering.xml"})
            rels_tree.write(rels_path, xml_declaration=True, encoding="UTF-8")

        content_types_path = tmp_path / "[Content_Types].xml"
        content_tree, content_root = _parse_part(content_types_path)
        numbering_content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
        if not any(override.get("PartName") == "/word/numbering.xml" for override in content_root):
            ET.SubElement(
                content_root,
                f"{{{content_namespace}}}Override",
                {"PartName": "/word/numbering.xml", "ContentType": numbering_content_type},
            )
            content_tree.write(content_types_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())


def _run_has_drawing(run: Any) -> bool:
    from docx.oxml.ns import qn

    return run._r.find(qn("w:drawing")) is not None or run._r.find(qn("w:pict")) is not None


def _transfer_drawing_run(run: Any, new_paragraph: Any, source_part: Any, dest_part: Any) -> None:
    # Inline images live as a <w:drawing> inside the run element, not in
    # run.text. Deep-copy the run XML and re-embed each referenced image part
    # into the destination package, remapping its relationship id.
    import copy

    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn

    new_r = copy.deepcopy(run._r)
    # Pandoc leaks the image's absolute source path into the picture's
    # non-visual description (`pic:cNvPr@descr`). Reduce it to its basename so
    # the assembled docx never depends on the build machine's paths (which
    # breaks byte identity across machines/workspaces) or ships local
    # directories inside the document -- same determinism guarantee as
    # normalize_docx_zip_timestamps, one layer up at the XML. The basename is
    # content-derived (`visual-<sha8>.png` / `fig-<name>.png`) and stable.
    for cnvpr in new_r.iter(qn("pic:cNvPr")):
        descr = cnvpr.get("descr")
        if descr and ("/" in descr or "\\" in descr):
            cnvpr.set("descr", descr.replace("\\", "/").rsplit("/", 1)[-1])
    for embed_attr in (qn("r:embed"), qn("r:link")):
        for blip in new_r.iter(qn("a:blip")):
            rid = blip.get(embed_attr)
            if rid:
                image_part = source_part.related_parts[rid]
                blip.set(embed_attr, dest_part.relate_to(image_part, RT.IMAGE))
    new_paragraph._p.append(new_r)


def add_fixed_text_page(document: Any, text: str, theme: VisualTheme | None = None) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    theme = theme or VisualTheme()
    paragraph.paragraph_format.line_spacing = theme.spacing.body_line_spacing
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(theme.spacing.body_after_pt)
    run = paragraph.add_run(text)
    run.font.name = theme.typography.body_font
    run.font.size = Pt(theme.typography.body_size_pt)


def add_image_page(document: Any, image_path: Path, caption: str = "") -> None:
    """Insert a scanned/rendered image (e.g. a signed release letter) as a
    centered, page-sized picture -- used by the `image_page` leading part to
    replace a blank guard page with an actual full-page document. Sized to fit
    the text area (width first; height-capped for very tall scans), so it never
    overflows the page.

    `caption` becomes the picture's alternative text. A whole page that IS an
    image is the worst place to omit it: a screen reader reaches it and
    announces nothing. Section figures already carry alt text because they go
    through pandoc, which writes `descr` from the markdown alt text; this path
    uses python-docx directly and has to set it itself.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm
    from PIL import Image

    max_w_cm, max_h_cm = 15.5, 21.5
    with Image.open(str(image_path)) as im:
        width_px, height_px = im.size

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = None
    run = paragraph.add_run()
    if width_px and (max_w_cm * (height_px / width_px)) <= max_h_cm:
        picture = run.add_picture(str(image_path), width=Cm(max_w_cm))
    else:
        picture = run.add_picture(str(image_path), height=Cm(max_h_cm))
    set_picture_alt_text(picture, caption or image_path.stem)


def set_picture_alt_text(picture: Any, description: str) -> None:
    """Write `<wp:docPr descr="...">` on an inline picture.

    python-docx exposes no API for this (it emits `docPr` with only `id` and
    `name`), so the attribute is set on the underlying element. Deterministic:
    an attribute value derived from declared config, never from the clock.
    """
    from docx.oxml.ns import qn

    doc_pr = picture._inline.find(qn("wp:docPr"))
    if doc_pr is not None:
        doc_pr.set("descr", description)


def apply_normative_paragraph_format(
    paragraph: Any, style_name: str | None, text: str, theme: VisualTheme, is_list: bool = False
) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph.paragraph_format.line_spacing = theme.spacing.body_line_spacing
    paragraph.paragraph_format.space_after = Pt(theme.spacing.body_after_pt)
    if style_name == "Heading 1":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.space_before = Pt(theme.spacing.heading_1_before_pt)
        paragraph.paragraph_format.space_after = Pt(theme.spacing.heading_1_after_pt)
    elif style_name == "Heading 2":
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.space_before = Pt(theme.spacing.heading_2_before_pt)
        paragraph.paragraph_format.space_after = Pt(theme.spacing.heading_2_after_pt)
    elif style_name == "Heading 3":
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.space_before = Pt(theme.spacing.heading_3_before_pt)
        paragraph.paragraph_format.space_after = Pt(theme.spacing.heading_3_after_pt)
    elif is_list:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.left_indent = Cm(0.63)
        set_bullet_numbering(paragraph)
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if text:
            paragraph.paragraph_format.first_line_indent = Cm(1.25)


def insert_toc_field(docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document(str(docx_path))
    matches = [p for p in document.paragraphs if (p.text or "").strip() == placeholder]
    if not matches:
        return False
    target, *leftovers = matches

    # A template that declares the index twice -- a `{"type": "toc"}` structure
    # part AND a section whose contract sets `toc: true` -- puts two
    # placeholders in the file. Only one may become a field, but the other
    # must NOT ship as visible text: `[[TOC]]` is harness syntax, never
    # authored prose. Removing it silently would hide the redundancy, so it
    # WARNs, the same degrade-and-say-why idiom the rest of the pipeline uses.
    for extra in leftovers:
        extra._p.getparent().remove(extra._p)
    if leftovers:
        print(
            f"WARN: se encontraron {len(matches)} marcadores {placeholder}; "
            f"solo el primero se convierte en índice y el resto se descarta. "
            f"Revisá el template: declarar una parte `toc` en `structure` Y una "
            f"sección con `toc: true` en su contrato son dos índices, no uno.",
            file=sys.stderr,
        )

    for run in list(target.runs)[::-1]:
        target._p.remove(run._r)

    run = target.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TOC \\o "{levels}" \\h \\z \\u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "(El indice se actualizara al abrir el documento en Word)"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
    document.save(str(docx_path))
    set_update_fields_on_open(docx_path)
    normalize_docx_zip_timestamps(docx_path)
    return True


def set_update_fields_on_open(docx_path: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", namespace)
    with tempfile.TemporaryDirectory(prefix="docs_docx_settings_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        settings_path = tmp_path / "word" / "settings.xml"
        if settings_path.exists():
            tree, root = _parse_part(settings_path)  # Design Decision 5.1 (defusedxml)
        else:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            root = ET.Element(f"{{{namespace}}}settings")
            tree = ET.ElementTree(root)

        update_fields = root.find(f"{{{namespace}}}updateFields")
        if update_fields is None:
            update_fields = ET.Element(f"{{{namespace}}}updateFields")
            root.insert(0, update_fields)
        update_fields.set(f"{{{namespace}}}val", "true")
        tree.write(settings_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())


class PythonDocxAssemblyAdapter:
    def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None:
        # pandoc is an external subprocess that writes `output` itself, so
        # (unlike the three write sites below that go through python-docx)
        # this harness never controls the zip entry timestamps or
        # docProps/core.xml dcterms values pandoc stamps into the file.
        # Normalize immediately after the subprocess succeeds so the body
        # .docx is deterministic like every other artifact this adapter
        # produces.
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_output = tempfile.mkstemp(
            prefix=f".{output.stem}.", suffix=output.suffix or ".docx", dir=output.parent
        )
        os.close(fd)
        temporary_path = Path(temporary_output)
        try:
            resource_dirs = sorted({str(Path(input_path).resolve().parent) for input_path in inputs})
            command = [pandoc_path, *map(str, inputs)]
            if resource_dirs:
                command.append(f"--resource-path={os.pathsep.join(resource_dirs)}")
            command.extend(["-o", str(temporary_path)])
            subprocess.run(
                command,
                check=True,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
            )
            if not temporary_path.exists() or temporary_path.stat().st_size == 0:
                raise RuntimeError("Pandoc produjo un DOCX vacío o inexistente")
            normalize_docx_zip_timestamps(temporary_path)
            os.replace(temporary_path, output)
        finally:
            temporary_path.unlink(missing_ok=True)

    def insert_toc_field(self, docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool:
        return insert_toc_field(docx_path, placeholder=placeholder, levels=levels)

    def _cover_base_document(
        self, config: dict[str, Any], cover_asset_path: Path | None, has_cover_from_asset_part: bool
    ):
        from docx import Document

        if has_cover_from_asset_part:
            if cover_asset_path and cover_asset_path.exists():
                return Document(str(cover_asset_path))
            return Document()
        template_docx = config.get("paths", {}).get("template_docx")
        if template_docx and Path(template_docx).exists():
            return Document(str(template_docx))
        return Document()

    def _build_main_document(self, config: dict[str, Any], body_docx: Path, cover_asset_path: Path | None):
        from docx import Document

        parts = structure_parts(config)
        idx = sections_index(parts)
        sections_part = parts[idx] if idx < len(parts) else {"type": "sections"}
        leading = parts[:idx]

        has_cover_from_asset_part = any(p.get("type") == "cover_from_asset" for p in leading)
        generated_cover = resolve_cover_spec(config)
        cover = (
            Document()
            if generated_cover and generated_cover.mode in {CoverMode.GENERATED, CoverMode.NONE}
            else self._cover_base_document(config, cover_asset_path, has_cover_from_asset_part)
        )
        if generated_cover and generated_cover.mode is CoverMode.GENERATED:
            compose_generated_cover(cover, generated_cover, config)
        body = Document(str(body_docx))

        self._configure_preliminary_pagination(cover, sections_part, config)
        effective_leading = leading
        if generated_cover and generated_cover.mode in {CoverMode.GENERATED, CoverMode.NONE}:
            # Explicit generated/none modes take precedence over a current
            # cover_from_asset part; otherwise the old cover is appended after
            # the generated one and silently wins the first-page visual QA.
            effective_leading = [part for part in leading if part.get("type") != "cover_from_asset"]
        self._render_leading_parts(cover, config, effective_leading)
        self._transfer_body_content(cover, body, sections_part, config)

        return cover

    def _configure_preliminary_pagination(self, cover: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.enum.section import WD_SECTION_START

        prelim_pag = sections_part.get("preliminary_pagination", {})
        prelim_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
        if prelim_pag:
            configure_roman_preliminary_section(prelim_section, config, int(prelim_pag.get("start", 2)))
            if prelim_pag.get("format"):
                set_section_page_number_start(
                    prelim_section, int(prelim_pag.get("start", 2)), prelim_pag["format"]
                )
        else:
            configure_unnumbered_section(prelim_section, config)

    def _resolve_leading_image_path(self, config: dict[str, Any], part: dict[str, Any]) -> Path:
        """An `image_page` part's `image` is either an absolute path or one
        relative to the document's `assets_dir` (portable, the same dir the
        section figures resolve against)."""
        raw = Path(str(part.get("image", "")))
        if raw.is_absolute():
            return raw
        assets_dir = config.get("paths", {}).get("assets_dir", "")
        return Path(assets_dir) / raw if assets_dir else raw

    def _render_leading_parts(self, cover: Any, config: dict[str, Any], leading: list[dict[str, Any]]) -> None:
        from docx.enum.text import WD_BREAK

        for part in leading:
            kind = part.get("type")
            if kind in {"cover_from_template", "cover_from_asset", "embed_docx", "sections"}:
                continue
            if kind == "blank_page":
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif kind == "image_page":
                add_image_page(
                    cover,
                    self._resolve_leading_image_path(config, part),
                    caption=str(part.get("caption", "")),
                )
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif kind in {"fixed_text_page", "toc"}:
                if kind == "toc":
                    cover.add_paragraph("[[TOC]]")
                else:
                    add_fixed_text_page(cover, resolve_part_text(config, part), resolve_visual_theme(config))
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def _body_transfer_context(self, sections_part: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        restart_id = sections_part.get("body_restart_section", "")
        restart_heading = ""
        if restart_id:
            section = next((s for s in config.get("sections", []) if s.get("id") == restart_id), None)
            restart_heading = normalize_heading(section["title"] if section else restart_id)
        return {
            "restart_heading": restart_heading,
            "body_pag": sections_part.get("body_pagination", {"format": "decimal", "start": 1}),
            "body_heading_seen": False,
            "restart_started": False,
            "just_broke": False,
        }

    def _iter_body_blocks(self, body: Any):
        # Walk block-level content (paragraphs AND tables) in DOCUMENT ORDER so
        # a table lands where it belongs, not appended after every paragraph.
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        if hasattr(body, "iter_inner_content"):
            yield from body.iter_inner_content()
            return
        for child in body.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, body)
            elif child.tag == qn("w:tbl"):
                yield Table(child, body)

    def _transfer_body_content(self, cover: Any, body: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.table import Table

        ctx = self._body_transfer_context(sections_part, config)
        table_theme = resolve_visual_theme(config) if has_visual_theme(config) else None
        for block in self._iter_body_blocks(body):
            if isinstance(block, Table):
                self._transfer_one_table(cover, block, table_theme)
            else:
                self._transfer_one_paragraph(cover, body, block, ctx, config)

    def _transfer_body_paragraphs(self, cover: Any, body: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        ctx = self._body_transfer_context(sections_part, config)
        for paragraph in body.paragraphs:
            self._transfer_one_paragraph(cover, body, paragraph, ctx, config)

    def _transfer_one_paragraph(self, cover: Any, body: Any, paragraph: Any, ctx: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.enum.section import WD_SECTION_START
        from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
        from docx.shared import Pt, RGBColor

        if paragraph.text.strip() == "[[pagebreak]]":
            # Same `[[...]]` marker family as `[[TOC]]`/`[[figure:]]`/`[[table:]]`.
            # A paragraph whose ENTIRE trimmed text is the marker becomes a
            # forced Word page break -- same emission the cover/TOC leading
            # parts already use (`_render_leading_parts`), so no stray empty
            # paragraph is left to shift pagination. A marker mixed with other
            # text is left as literal text (falls through below), matching
            # every other marker family's sole-content rule.
            #
            # `just_broke` dedupes adjacent breaks: a marker right after another
            # break (another marker, or a heading auto-break) is swallowed, and
            # a marker right BEFORE an auto-breaking Heading 1 lets that
            # heading's own break stand alone (the `not ctx["just_broke"]` guard
            # below) -- either way one blank between them, never a fully blank
            # page. ponytail: covers the marker<->heading/marker cases; a marker
            # immediately before the pagination-restart heading still double-
            # breaks (that heading's section-start forces its own page), an
            # exotic combo no real document hits.
            if not ctx["just_broke"]:
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
                ctx["just_broke"] = True
            return

        restart_heading = ctx["restart_heading"]
        body_pag = ctx["body_pag"]
        style_name = safe_style_name(cover, paragraph.style.name if paragraph.style else None)
        is_list = paragraph_has_numbering(paragraph)
        if is_list:
            style_name = safe_style_name(cover, "List Bullet") or style_name
        paragraph_text = paragraph.text.strip()
        is_heading_1 = style_name == "Heading 1"
        is_restart = is_heading_1 and restart_heading and normalize_heading(paragraph_text) == restart_heading
        if is_restart and not ctx["restart_started"]:
            numbered_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
            configure_numbered_body_section(numbered_section, config)
            set_section_page_number_start(
                numbered_section, int(body_pag.get("start", 1)), body_pag.get("format", "decimal")
            )
            ctx["restart_started"] = True
        page_break_before = is_heading_1 and ctx["body_heading_seen"] and not ctx["just_broke"]
        ctx["just_broke"] = False
        new_paragraph = cover.add_paragraph(style=style_name)
        theme = resolve_visual_theme(config)
        apply_normative_paragraph_format(new_paragraph, style_name, paragraph_text, theme, is_list=is_list)
        if page_break_before:
            new_paragraph.paragraph_format.page_break_before = True
        # Academic figure layout: an image paragraph and its caption are centered
        # (never left-aligned or first-line-indented), and the image keeps with
        # the next paragraph so its "Figura N." caption never orphans onto the
        # following page. Normal body paragraphs are untouched.
        if any(_run_has_drawing(run) for run in paragraph.runs):
            new_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            new_paragraph.paragraph_format.first_line_indent = None
            new_paragraph.paragraph_format.keep_with_next = True
            # An image hugs its caption: a small gap (not the 18pt body spacing)
            # keeps "Figura N." directly under the figure it labels.
            new_paragraph.paragraph_format.space_after = Pt(6)
        elif caption_match := _CAPTION_RE.match(paragraph_text):
            new_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            new_paragraph.paragraph_format.first_line_indent = None
            # A "Tabla N." caption sits ABOVE its table -- keep it with the table
            # so it never orphans at a page bottom. (A "Figura N." caption sits
            # below its image, which already keeps_with_next onto the caption.)
            if caption_match.group(1).lower().startswith("tabla"):
                new_paragraph.paragraph_format.keep_with_next = True
        if is_heading_1:
            ctx["body_heading_seen"] = True
        for run in paragraph.runs:
            if _run_has_drawing(run):
                _transfer_drawing_run(run, new_paragraph, body.part, cover.part)
                continue
            new_run = new_paragraph.add_run(run.text)
            new_run.bold = run.bold
            new_run.italic = run.italic
            new_run.underline = run.underline
            if style_name == "Heading 1":
                new_run.font.name = theme.typography.heading_font
                new_run.font.size = Pt(theme.typography.heading_1_size_pt)
                new_run.font.color.rgb = RGBColor.from_string(theme.colors.heading_1)
            elif style_name == "Heading 2":
                new_run.font.name = theme.typography.heading_font
                new_run.font.size = Pt(theme.typography.heading_2_size_pt)
                new_run.font.color.rgb = RGBColor.from_string(theme.colors.heading_2)
            elif style_name == "Heading 3":
                new_run.font.name = theme.typography.heading_font
                new_run.font.size = Pt(theme.typography.heading_3_size_pt)
                new_run.font.color.rgb = RGBColor.from_string(theme.colors.heading_3)
            else:
                new_run.font.name = theme.typography.body_font
                new_run.font.size = Pt(theme.typography.body_size_pt)
                new_run.font.color.rgb = RGBColor(0, 0, 0)
            if _CAPTION_RE.match(paragraph_text):
                new_run.font.color.rgb = RGBColor.from_string(_theme_color(theme, theme.captions.color))

    def _transfer_body_tables(self, cover: Any, body: Any) -> None:
        for table in body.tables:
            self._transfer_one_table(cover, table)

    def _transfer_one_table(self, cover: Any, table: Any, theme: VisualTheme | None = None) -> None:
        from docx.oxml import OxmlElement
        from docx.shared import Pt

        new_table = cover.add_table(rows=len(table.rows), cols=len(table.columns))
        self._apply_horizontal_only_borders(new_table)
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                new_cell = new_table.cell(row_idx, col_idx)
                new_cell.text = cell.text
                for paragraph in new_cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.name = theme.typography.body_font if theme else "Times New Roman"
                        if theme:
                            run.font.size = Pt(theme.typography.body_size_pt)
                        if row_idx == 0:
                            run.bold = True
        # Multi-page table hygiene: keep each row intact across page boundaries
        # (`cantSplit`) and repeat the header row on every page the table spans
        # (`tblHeader`), so a table that breaks never strands a header or splits
        # a row mid-cell.
        for row_idx, new_row in enumerate(new_table.rows):
            tr_pr = new_row._tr.get_or_add_trPr()
            tr_pr.append(OxmlElement("w:cantSplit"))
            if row_idx == 0:
                tr_pr.append(OxmlElement("w:tblHeader"))

    def _apply_horizontal_only_borders(self, table: Any) -> None:
        # Institutional guide: horizontal lines only, no vertical lines, no
        # shading. Emit only top/bottom/insideH borders. Vertical edges are
        # deliberately OMITTED (not set to "nil"): the format audit
        # (`table_has_vertical_borders_or_shading`) flags the mere presence of
        # <w:left|right|insideV>, so declaring them — even as nil — would fail
        # it, and a default python-docx table renders no vertical rule anyway.
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "bottom", "insideH"):
            element = OxmlElement(f"w:{edge}")
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), "4")
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), "000000")
            borders.append(element)
        table._tbl.tblPr.append(borders)

    def assemble(
        self,
        config: dict[str, Any],
        body_docx: Path,
        output_docx: Path,
        *,
        cover_asset_path: Path | None,
        embed_front_paths: list[Path],
        embed_back_paths: list[Path],
    ) -> None:
        from docx import Document

        output_docx.parent.mkdir(parents=True, exist_ok=True)
        parts = structure_parts(config)
        has_cover_from_asset = any(
            p.get("type") == "cover_from_asset" for p in parts[: sections_index(parts)]
        )
        main = self._build_main_document(config, body_docx, cover_asset_path if has_cover_from_asset else None)

        if not embed_front_paths and not embed_back_paths:
            main.save(str(output_docx))
            ensure_bullet_numbering_part(output_docx)
            normalize_docx_zip_timestamps(output_docx)
            return

        with tempfile.TemporaryDirectory(prefix="docs_assemble_") as tmp:
            main_path = Path(tmp) / "main.docx"
            main.save(str(main_path))
            ensure_bullet_numbering_part(main_path)
            try:
                from docxcompose.composer import Composer
            except Exception as exc:
                raise RuntimeError(
                    f"docxcompose no está disponible (requerido para embeber .docx): {exc}. "
                    "Instala con `pip install docxcompose`."
                ) from exc
            ordered = [*embed_front_paths, main_path, *embed_back_paths]
            master = Document(str(ordered[0]))
            composer = Composer(master)
            for piece in ordered[1:]:
                composer.append(Document(str(piece)))
            composer.save(str(output_docx))
            normalize_docx_zip_timestamps(output_docx)
