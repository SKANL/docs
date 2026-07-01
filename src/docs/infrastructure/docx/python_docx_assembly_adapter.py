from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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


# --- Slice 11b stub seam -----------------------------------------------------
# These are local no-op placeholders for real OOXML layout helpers that a
# future Slice 11b ("DOCX Layout & TOC") will add. Slice 11a's own scope
# excludes Word-correct page numbering, TOC insertion, and bullet-glyph
# rendering (see plans/2026-06-22-slice-11-docx-assembly.md). When Slice 11b
# lands, these stubs and their call sites below (in `_build_main_document`,
# `apply_normative_paragraph_format`, and `assemble`) are deleted and
# repointed to the real implementations.


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


def _configure_roman_preliminary_section_stub(section: Any, config: dict[str, Any], start: int = 2) -> None:
    # Placeholder for Slice 11b's configure_roman_preliminary_section. No-op.
    pass


def _configure_unnumbered_section_stub(section: Any, config: dict[str, Any]) -> None:
    # Placeholder for Slice 11b's configure_unnumbered_section. No-op.
    pass


def _configure_numbered_body_section_stub(section: Any, config: dict[str, Any]) -> None:
    # Placeholder for Slice 11b's configure_numbered_body_section. No-op.
    pass


def _set_section_page_number_start_stub(section: Any, start: int, fmt: str | None = None) -> None:
    # Placeholder for Slice 11b's set_section_page_number_start. No-op.
    pass


def _ensure_bullet_numbering_part_stub(docx_path: Path, num_id: int = 42) -> None:
    # Placeholder for Slice 11b's ensure_bullet_numbering_part. No-op.
    pass


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


class PythonDocxAssemblyAdapter:
    def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None:
        subprocess.run([pandoc_path, *map(str, inputs), "-o", str(output)], check=True)

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
        from docx.enum.section import WD_SECTION_START
        from docx.enum.text import WD_BREAK
        from docx.shared import Pt, RGBColor

        parts = structure_parts(config)
        sections_index = self._sections_index(parts)
        sections_part = parts[sections_index] if sections_index < len(parts) else {"type": "sections"}
        leading = parts[:sections_index]

        has_cover_from_asset_part = any(p.get("type") == "cover_from_asset" for p in leading)
        cover = self._cover_base_document(config, cover_asset_path, has_cover_from_asset_part)
        body = Document(str(body_docx))

        prelim_pag = sections_part.get("preliminary_pagination", {})
        prelim_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
        if prelim_pag:
            _configure_roman_preliminary_section_stub(prelim_section, config, int(prelim_pag.get("start", 2)))
            if prelim_pag.get("format"):
                _set_section_page_number_start_stub(
                    prelim_section, int(prelim_pag.get("start", 2)), prelim_pag["format"]
                )
        else:
            _configure_unnumbered_section_stub(prelim_section, config)

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
                _configure_numbered_body_section_stub(numbered_section, config)
                _set_section_page_number_start_stub(
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

        for table in body.tables:
            new_table = cover.add_table(rows=len(table.rows), cols=len(table.columns))
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    new_table.cell(row_idx, col_idx).text = cell.text

        return cover

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
            _ensure_bullet_numbering_part_stub(output_docx)
            return

        with tempfile.TemporaryDirectory(prefix="docs_assemble_") as tmp:
            main_path = Path(tmp) / "main.docx"
            main.save(str(main_path))
            _ensure_bullet_numbering_part_stub(main_path)
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
