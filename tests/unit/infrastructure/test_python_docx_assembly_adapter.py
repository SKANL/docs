import base64
import io

from docx import Document
from docx.oxml.ns import qn

from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter

# 1x1 pixel PNG, same fixture used across the ingest tests.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def test_transfer_body_tables_copies_cell_text_into_new_table():
    adapter = PythonDocxAssemblyAdapter()
    cover = Document()
    body = Document()
    table = body.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "a"
    table.cell(0, 1).text = "b"
    table.cell(1, 0).text = "c"
    table.cell(1, 1).text = "d"

    adapter._transfer_body_tables(cover, body)

    assert len(cover.tables) == 1
    new_table = cover.tables[0]
    assert new_table.cell(0, 0).text == "a"
    assert new_table.cell(1, 1).text == "d"


def _block_sequence(document):
    """Ordered list of block kinds for a document body: 'table' for each
    table, or the stripped text for each non-empty paragraph."""
    from docx.table import Table

    sequence = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            sequence.append("table")
        else:
            text = block.text.strip()
            if text:
                sequence.append(text)
    return sequence


def test_body_tables_are_transferred_in_document_order(tmp_path):
    # A body with: Heading-1 "A", a table, paragraph "B". The table belongs
    # BETWEEN A and B, not appended after the last paragraph.
    body_docx = tmp_path / "body.docx"
    body = Document()
    body.add_paragraph("A", style="Heading 1")
    table = body.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "cell-x"
    table.cell(0, 1).text = "cell-y"
    body.add_paragraph("B")
    body.save(str(body_docx))

    adapter = PythonDocxAssemblyAdapter()
    config = {"structure": [{"type": "sections"}]}
    main = adapter._build_main_document(config, body_docx, None)

    sequence = _block_sequence(main)
    assert "A" in sequence and "B" in sequence and "table" in sequence
    a_idx = sequence.index("A")
    b_idx = sequence.index("B")
    table_idx = sequence.index("table")
    assert a_idx < table_idx < b_idx, sequence


def test_transferred_table_has_horizontal_only_borders_no_shading():
    from docs.infrastructure.docx.python_docx_audit_adapter import (
        table_has_vertical_borders_or_shading,
    )

    adapter = PythonDocxAssemblyAdapter()
    cover = Document()
    body = Document()
    table = body.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "head-a"
    table.cell(0, 1).text = "head-b"
    table.cell(1, 0).text = "line1\nline2"
    table.cell(1, 1).text = "d"

    adapter._transfer_body_tables(cover, body)

    new_table = cover.tables[0]
    xml = new_table._tbl.xml
    # Horizontal borders are declared.
    assert "<w:tblBorders" in xml
    borders = new_table._tbl.tblPr.find(qn("w:tblBorders"))
    assert borders is not None
    for edge in ("top", "bottom", "insideH"):
        el = borders.find(qn(f"w:{edge}"))
        assert el is not None and el.get(qn("w:val")) == "single"
    # Must PASS the institutional audit: no vertical borders, no shading.
    assert table_has_vertical_borders_or_shading(new_table) is False
    # Multi-line cell text is preserved.
    assert "line1" in new_table.cell(1, 0).text
    assert "line2" in new_table.cell(1, 0).text


def test_transfer_body_paragraphs_preserves_inline_images():
    adapter = PythonDocxAssemblyAdapter()
    cover = Document()
    body = Document()

    paragraph = body.add_paragraph()
    paragraph.add_run("before ")
    paragraph.add_run().add_picture(io.BytesIO(_PIXEL_PNG))
    paragraph.add_run(" after")

    adapter._transfer_body_paragraphs(cover, body, {}, {})

    # The transferred paragraph must carry the inline drawing, not just text.
    drawings = cover.element.body.findall(f".//{qn('w:drawing')}")
    assert len(drawings) >= 1
    # The image part must be embedded into the destination package.
    assert len(cover.inline_shapes) >= 1
    # Text runs around the image are still preserved in order.
    transferred_text = "".join(p.text for p in cover.paragraphs)
    assert "before" in transferred_text
    assert "after" in transferred_text


def test_visual_theme_merges_defaults_and_normalizes_hex_colors():
    from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_visual_theme

    theme = resolve_visual_theme(
        {
            "format": {
                "visual_theme": {
                    "colors": {"navy": "#0b1f33", "teal": "0f766e"},
                    "typography": {"body_font": "Aptos", "body_size_pt": 11},
                    "spacing": {"body_line_spacing": 1.25, "heading_1_after_pt": 10},
                    "header": {"title": "CISSP DOMAIN 6"},
                    "footer": {"font_size_pt": 9},
                }
            }
        }
    )

    assert theme.colors.navy == "0B1F33"
    assert theme.colors.teal == "0F766E"
    assert theme.typography.body_font == "Aptos"
    assert theme.typography.body_size_pt == 11
    assert theme.spacing.body_line_spacing == 1.25
    assert theme.spacing.heading_1_after_pt == 10
    assert theme.header.title == "CISSP DOMAIN 6"
    assert theme.footer.font_size_pt == 9
    # Partial themes retain current behavior for every unspecified value.
    assert theme.typography.heading_font == "Times New Roman"
    assert theme.spacing.body_after_pt == 18


def test_visual_theme_applies_body_heading_caption_header_and_footer_styles(tmp_path):
    from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter

    body_path = tmp_path / "body.docx"
    body = Document()
    body.add_paragraph("DOMAIN 6", style="Heading 1")
    body.add_paragraph("Body paragraph.")
    body.add_paragraph("Figura 1. A figure caption.")
    body.save(str(body_path))

    config = {
        "format": {
            "visual_theme": {
                "colors": {"navy": "0B1F33", "teal": "0F766E", "warm_accent": "D97706"},
                "typography": {
                    "body_font": "Aptos",
                    "body_size_pt": 11,
                    "heading_font": "Aptos Display",
                    "heading_1_size_pt": 18,
                },
                "spacing": {"body_line_spacing": 1.25, "body_after_pt": 8, "heading_1_after_pt": 12},
                "header": {"title": "CISSP DOMAIN 6", "accent_color": "teal"},
                "footer": {"font_size_pt": 9, "color": "teal"},
                "captions": {"color": "warm_accent"},
            }
        },
        "structure": [
            {"type": "sections", "body_restart_section": "domain", "body_pagination": {"format": "decimal"}}
        ],
        "sections": [{"id": "domain", "title": "DOMAIN 6"}],
    }

    document = PythonDocxAssemblyAdapter()._build_main_document(config, body_path, None)
    heading, body_paragraph, caption = [p for p in document.paragraphs if p.text.strip()][-3:]

    assert heading.runs[0].font.name == "Aptos Display"
    assert str(heading.runs[0].font.color.rgb) == "0B1F33"
    assert heading.paragraph_format.space_after.pt == 12
    assert body_paragraph.runs[0].font.name == "Aptos"
    assert body_paragraph.runs[0].font.size.pt == 11
    assert body_paragraph.paragraph_format.line_spacing == 1.25
    assert body_paragraph.paragraph_format.space_after.pt == 8
    assert str(caption.runs[0].font.color.rgb) == "D97706"
    assert document.sections[-1].header.paragraphs[0].text == "CISSP DOMAIN 6"
    assert document.sections[-1].footer.paragraphs[0].runs[0].font.size.pt == 9


def test_no_visual_theme_preserves_current_table_and_footer_run_ooxml(tmp_path):
    """A theme-free document must not acquire explicit visual overrides."""
    body_path = tmp_path / "body.docx"
    body = Document()
    body.add_paragraph("DOMAIN 6", style="Heading 1")
    body.add_table(rows=1, cols=1).cell(0, 0).text = "Current table value"
    body.save(str(body_path))

    config = {
        "structure": [
            {"type": "sections", "body_restart_section": "domain", "body_pagination": {"format": "decimal"}}
        ],
        "sections": [{"id": "domain", "title": "DOMAIN 6"}],
    }

    document = PythonDocxAssemblyAdapter()._build_main_document(config, body_path, None)

    table_run = document.tables[0].cell(0, 0).paragraphs[0].runs[0]
    footer_run = document.sections[-1].footer.paragraphs[0].runs[0]
    assert table_run.font.size is None
    assert table_run.font.color.rgb is None
    assert footer_run.font.color.rgb is None


def test_visual_theme_uses_configured_semantic_heading_colors(tmp_path):
    body_path = tmp_path / "body.docx"
    body = Document()
    body.add_paragraph("LEVEL ONE", style="Heading 1")
    body.add_paragraph("Level two", style="Heading 2")
    body.add_paragraph("Level three", style="Heading 3")
    body.save(str(body_path))

    config = {
        "format": {
            "visual_theme": {
                "colors": {"heading_1": "D97706", "heading_2": "2563EB", "heading_3": "BE123C"}
            }
        },
        "structure": [{"type": "sections"}],
    }

    document = PythonDocxAssemblyAdapter()._build_main_document(config, body_path, None)
    headings = [paragraph for paragraph in document.paragraphs if paragraph.text.strip()][-3:]

    assert str(headings[0].runs[0].font.color.rgb) == "D97706"
    assert str(headings[1].runs[0].font.color.rgb) == "2563EB"
    assert str(headings[2].runs[0].font.color.rgb) == "BE123C"
