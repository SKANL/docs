from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from defusedxml.ElementTree import parse as safe_parse

from docs.domain.docx_structure import resolve_part_text, structure_parts
from docs.domain.markdown_text import normalize_heading
from docs.infrastructure.docx.python_docx_audit_adapter import paragraph_has_numbering


def resolve_pandoc_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("pandoc")
    if resolved:
        return resolved
    configured = paths.get("pandoc_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("pandoc_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None


def safe_style_name(document: Any, preferred_style: str | None) -> str | None:
    available = {style.name for style in document.styles}
    if preferred_style in available:
        return preferred_style

    pandoc_style_map = {
        "First Paragraph": "No Spacing",
        "Body Text": "No Spacing",
        "Compact": "No Spacing",
    }
    mapped = pandoc_style_map.get(preferred_style or "")
    if mapped in available:
        return mapped
    if "Normal" in available:
        return "Normal"
    if "No Spacing" in available:
        return "No Spacing"
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


def configure_numbered_body_section(section: Any, config: dict[str, Any]) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    add_page_number_footer(section.footer)
    set_section_page_number_start(section, 1, "decimal")


def configure_roman_preliminary_section(section: Any, config: dict[str, Any], start: int = 2) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    add_page_number_footer(section.footer)
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


def add_page_number_footer(footer: Any) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    paragraph = footer.paragraphs[-1] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)

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
            numbering_tree = safe_parse(numbering_path)
            numbering_root = numbering_tree.getroot()
        else:
            numbering_path.parent.mkdir(parents=True, exist_ok=True)
            numbering_root = ET.Element(f"{{{namespace}}}numbering")
            numbering_tree = ET.ElementTree(numbering_root)

        if not numbering_root.find(f".//{{{namespace}}}num[@{{{namespace}}}numId='{num_id}']"):
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
        rels_tree = safe_parse(rels_path)
        rels_root = rels_tree.getroot()
        numbering_rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        if not any(rel.get("Type") == numbering_rel_type for rel in rels_root):
            existing_ids = [int(match.group(1)) for rel in rels_root for match in [re.match(r"rId(\d+)$", rel.get("Id", ""))] if match]
            next_id = max(existing_ids or [0]) + 1
            ET.SubElement(rels_root, f"{{{rel_namespace}}}Relationship", {"Id": f"rId{next_id}", "Type": numbering_rel_type, "Target": "numbering.xml"})
            rels_tree.write(rels_path, xml_declaration=True, encoding="UTF-8")

        content_types_path = tmp_path / "[Content_Types].xml"
        content_tree = safe_parse(content_types_path)
        content_root = content_tree.getroot()
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


def add_fixed_text_page(document: Any, text: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(18)
    run = paragraph.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)


def apply_normative_paragraph_format(paragraph: Any, style_name: str | None, text: str, is_list: bool = False) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.space_after = Pt(18)
    if style_name == "Heading 1":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = None
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
    target = None
    for paragraph in document.paragraphs:
        if (paragraph.text or "").strip() == placeholder:
            target = paragraph
            break
    if target is None:
        return False

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
            tree = safe_parse(settings_path)  # Design Decision 5.1 (defusedxml)
            root = tree.getroot()
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
        subprocess.run([pandoc_path, *map(str, inputs), "-o", str(output)], check=True)

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
        sections_index = self._sections_index(parts)
        sections_part = parts[sections_index] if sections_index < len(parts) else {"type": "sections"}
        leading = parts[:sections_index]

        has_cover_from_asset_part = any(p.get("type") == "cover_from_asset" for p in leading)
        cover = self._cover_base_document(config, cover_asset_path, has_cover_from_asset_part)
        body = Document(str(body_docx))

        self._configure_preliminary_pagination(cover, sections_part, config)
        self._render_leading_parts(cover, config, leading)
        self._transfer_body_paragraphs(cover, body, sections_part, config)
        self._transfer_body_tables(cover, body)

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

    def _render_leading_parts(self, cover: Any, config: dict[str, Any], leading: list[dict[str, Any]]) -> None:
        from docx.enum.text import WD_BREAK

        for part in leading:
            kind = part.get("type")
            if kind in {"cover_from_template", "cover_from_asset", "embed_docx", "sections"}:
                continue
            if kind == "blank_page":
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif kind in {"fixed_text_page", "toc"}:
                if kind == "toc":
                    cover.add_paragraph("[[TOC]]")
                else:
                    add_fixed_text_page(cover, resolve_part_text(config, part))
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def _transfer_body_paragraphs(self, cover: Any, body: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.enum.section import WD_SECTION_START
        from docx.enum.text import WD_BREAK
        from docx.shared import Pt, RGBColor

        restart_id = sections_part.get("body_restart_section", "")
        restart_heading = ""
        if restart_id:
            section = next((s for s in config.get("sections", []) if s.get("id") == restart_id), None)
            restart_heading = normalize_heading(section["title"] if section else restart_id)
        body_pag = sections_part.get("body_pagination", {"format": "decimal", "start": 1})

        body_heading_seen = False
        restart_started = False
        for paragraph in body.paragraphs:
            style_name = safe_style_name(cover, paragraph.style.name if paragraph.style else None)
            is_list = paragraph_has_numbering(paragraph)
            if is_list:
                style_name = safe_style_name(cover, "List Bullet") or style_name
            paragraph_text = paragraph.text.strip()
            is_heading_1 = style_name == "Heading 1"
            is_restart = is_heading_1 and restart_heading and normalize_heading(paragraph_text) == restart_heading
            if is_restart and not restart_started:
                numbered_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
                configure_numbered_body_section(numbered_section, config)
                set_section_page_number_start(
                    numbered_section, int(body_pag.get("start", 1)), body_pag.get("format", "decimal")
                )
                restart_started = True
            elif is_heading_1 and body_heading_seen:
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            new_paragraph = cover.add_paragraph(style=style_name)
            apply_normative_paragraph_format(new_paragraph, style_name, paragraph_text, is_list=is_list)
            if is_heading_1:
                body_heading_seen = True
            for run in paragraph.runs:
                new_run = new_paragraph.add_run(run.text)
                new_run.bold = run.bold
                new_run.italic = run.italic
                new_run.underline = run.underline
                new_run.font.name = "Times New Roman"
                new_run.font.size = Pt(12)
                new_run.font.color.rgb = RGBColor(0, 0, 0)

    def _transfer_body_tables(self, cover: Any, body: Any) -> None:
        for table in body.tables:
            new_table = cover.add_table(rows=len(table.rows), cols=len(table.columns))
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    new_table.cell(row_idx, col_idx).text = cell.text

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
            p.get("type") == "cover_from_asset" for p in parts[: self._sections_index(parts)]
        )
        main = self._build_main_document(config, body_docx, cover_asset_path if has_cover_from_asset else None)

        if not embed_front_paths and not embed_back_paths:
            main.save(str(output_docx))
            ensure_bullet_numbering_part(output_docx)
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

    @staticmethod
    def _sections_index(parts: list[dict[str, Any]]) -> int:
        return next((i for i, p in enumerate(parts) if p.get("type") == "sections"), len(parts))
