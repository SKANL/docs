from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter


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
