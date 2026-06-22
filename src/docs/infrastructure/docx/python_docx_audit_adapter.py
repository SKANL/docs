# src/docs/infrastructure/docx/python_docx_audit_adapter.py
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from docs.domain.docx_structure import margins_match, non_cover_margin_emu, resolve_part_text, structure_parts
from docs.domain.markdown_text import normalize_heading
from docs.domain.review import Issue


def _section_margin_emu(section: Any) -> dict[str, int]:
    return {
        "top": int(section.top_margin or 0),
        "right": int(section.right_margin or 0),
        "bottom": int(section.bottom_margin or 0),
        "left": int(section.left_margin or 0),
    }


def table_has_vertical_borders_or_shading(table: Any) -> bool:
    xml = table._tbl.xml
    if re.search(r"<w:(left|right|insideV)\b", xml):
        return True
    return "<w:shd" in xml


def paragraph_has_numbering(paragraph: Any) -> bool:
    p_pr = paragraph._p.pPr
    return bool(p_pr is not None and p_pr.numPr is not None)


class PythonDocxAuditAdapter:
    def list_parts(self, docx_path: Path, prefix: str) -> list[str]:
        with zipfile.ZipFile(docx_path) as archive:
            return sorted(name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".xml"))

    def read_xml(self, docx_path: Path, part_name: str) -> str:
        with zipfile.ZipFile(docx_path) as archive:
            try:
                return archive.read(part_name).decode("utf-8")
            except KeyError:
                return ""

    def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]:
        from docx import Document
        from docx.shared import Cm, Pt

        document = Document(str(docx_path))
        issues: list[Issue] = []
        headings = [(p.style.name if p.style else "", p.text.strip()) for p in document.paragraphs if p.text.strip()]
        heading_texts = [text for style, text in headings if style.startswith("Heading")]

        parts = structure_parts(config)
        sections_part = next((p for p in parts if p.get("type") == "sections"), {})
        fixed_texts = [resolve_part_text(config, p) for p in parts if p.get("type") == "fixed_text_page"]
        prelim_pag = sections_part.get("preliminary_pagination", {})
        body_pag = sections_part.get("body_pagination", {})
        restart_id = sections_part.get("body_restart_section", "")
        restart_title = ""
        if restart_id:
            section = next((s for s in config.get("sections", []) if s.get("id") == restart_id), None)
            restart_title = section["title"] if section else restart_id

        if strict and restart_id and len(document.sections) < 2:
            issues.append(Issue("error", "El DOCX no tiene secciones suficientes para el reinicio de paginación del cuerpo."))
        if strict and restart_title and not any(normalize_heading(restart_title) in normalize_heading(text) for text in heading_texts):
            issues.append(Issue("warning", f"No se detectó el título `{restart_title}`; no puede verificarse el reinicio de paginación."))
        if strict:
            docx_xml = self.read_xml(docx_path, "word/document.xml")
            footer_xml = "\n".join(self.read_xml(docx_path, name) for name in self.list_parts(docx_path, "word/footer"))
            for fixed_text in fixed_texts:
                if fixed_text and fixed_text not in docx_xml:
                    issues.append(Issue("error", "No se encontró una página de texto fijo declarada en la estructura."))
            paginated = 0
            if prelim_pag.get("format"):
                paginated += 1
                start = prelim_pag.get("start", 2)
                fmt = prelim_pag["format"]
                if not re.search(rf"<w:pgNumType\b[^>]*w:start=\"{start}\"[^>]*w:fmt=\"{fmt}\"|<w:pgNumType\b[^>]*w:fmt=\"{fmt}\"[^>]*w:start=\"{start}\"", docx_xml):
                    issues.append(Issue("error", "No se detectó la paginación de preliminares declarada en la estructura."))
            if body_pag.get("format"):
                paginated += 1
                if not re.search(rf"<w:pgNumType\b[^>]*w:start=\"{body_pag.get('start', 1)}\"", docx_xml):
                    issues.append(Issue("error", "La sección del cuerpo no reinicia la paginación según la estructura."))
            if paginated:
                if "PAGE" not in footer_xml:
                    issues.append(Issue("error", "No se encontró campo PAGE en el pie de página de las secciones numeradas."))
                if 'w:jc w:val="right"' not in footer_xml:
                    issues.append(Issue("error", "El campo de paginación no está alineado a la derecha."))
                if footer_xml.count("PAGE") < paginated:
                    issues.append(Issue("error", "Faltan campos PAGE para las secciones paginadas declaradas."))
            expected_margins = non_cover_margin_emu(config)
            if expected_margins:
                for section_index, section in enumerate(document.sections):
                    if section_index == 0:
                        continue
                    actual_margins = _section_margin_emu(section)
                    if not margins_match(actual_margins, expected_margins):
                        issues.append(
                            Issue(
                                "error",
                                f"La sección {section_index + 1} no conserva márgenes de 2.5 cm en todos los lados.",
                            )
                        )
                        break

        for style, text in headings:
            if style == "Heading 1" and text != text.upper():
                issues.append(Issue("warning", f"Título de primer orden no está en mayúsculas sostenidas: `{text}`."))
            if style == "Heading 1" and re.match(r"^\d+(\.\d+)*\s+", text):
                issues.append(Issue("warning", f"Título de primer orden parece numerado manualmente: `{text}`."))

        for idx, table in enumerate(document.tables, start=1):
            if table_has_vertical_borders_or_shading(table):
                issues.append(Issue("error", f"Tabla {idx} contiene bordes verticales o sombreado; el manual exige sólo líneas horizontales sin colores."))

        body_start = 0
        for i, paragraph in enumerate(document.paragraphs):
            if paragraph.style and paragraph.style.name == "Heading 1":
                body_start = i
                break
        image_paragraphs = [
            i
            for i, p in enumerate(document.paragraphs[body_start:], start=body_start)
            if "<w:drawing" in p._p.xml or "<w:pict" in p._p.xml
        ]
        for paragraph_index in image_paragraphs:
            next_text = ""
            if paragraph_index + 1 < len(document.paragraphs):
                next_text = document.paragraphs[paragraph_index + 1].text.strip()
            if not re.match(r"^Figura\s+\d+\.", next_text, re.IGNORECASE):
                issues.append(Issue("warning", "Figura detectada sin caption inferior con patrón `Figura N.`."))

        if strict:
            for paragraph in document.paragraphs[body_start:]:
                text = paragraph.text.strip()
                style_name = paragraph.style.name if paragraph.style else ""
                if not text or style_name == "Heading 1":
                    continue
                paragraph_format = paragraph.paragraph_format
                if paragraph_format.line_spacing != 1.5:
                    issues.append(Issue("error", f"Párrafo sin interlineado 1.5: `{text[:60]}`."))
                    break
                if paragraph_format.space_after != Pt(18):
                    issues.append(Issue("error", f"Párrafo sin espacio posterior de 18 pt: `{text[:60]}`."))
                    break
                if style_name.startswith("List") or paragraph_has_numbering(paragraph):
                    if paragraph_format.first_line_indent not in {None, 0}:
                        issues.append(Issue("error", f"Lista con sangría inicial no permitida: `{text[:60]}`."))
                        break
                    continue
                if paragraph_format.first_line_indent is None or abs(paragraph_format.first_line_indent - Cm(1.25)) > 10000:
                    issues.append(Issue("error", f"Párrafo ordinario sin sangría inicial de 1.25 cm: `{text[:60]}`."))
                    break

        return issues
