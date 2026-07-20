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
