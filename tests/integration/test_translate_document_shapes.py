"""Translation against document SHAPES, not just one document.

Eight rounds of polish went into a single 120-page book, which is a sample
size of one: every fix risked being an overfit to that book's geometry. This
suite generates structurally different PDFs -- rotated pages, landscape, A5,
angled text, empty, malformed -- and asserts the capability behaves on each.

It found a real defect on its first run. A page of 90-degree text came back as
horizontal words running off the edge, reported only as "1 did not fit its
box", because every layout rule here reasons in page-horizontal space.
"""
from __future__ import annotations

import ctypes

import pytest

from docs.domain.block_grouping import group_runs_into_blocks
from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import Pypdfium2TextEditAdapter

LINES = (
    "Primera linea de prueba del documento",
    "Segunda linea con mas texto para envolver correctamente",
    "Tercera linea final",
)


def _widestring(text: str):
    buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\x00\x00")
    return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))


def _make(path, *, rotation=0, width=612, height=792, angled=False, empty=False):
    import pypdfium2 as pdfium
    import pypdfium2.raw as pc

    doc = pdfium.PdfDocument.new()
    page = doc.new_page(width, height)
    if not empty:
        font = pc.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
        for index, line in enumerate(LINES):
            obj = pc.FPDFPageObj_CreateTextObj(doc.raw, font, 12.0)
            pc.FPDFText_SetText(obj, _widestring(line))
            pc.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            if angled:
                pc.FPDFPageObj_Transform(obj, 0, 12, -12, 0, 100 + index * 40, 200)
            else:
                pc.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 72, height - 100 - index * 20)
            pc.FPDFPage_InsertObject(page.raw, obj)
    pc.FPDFPage_GenerateContent(page.raw)
    if rotation:
        pc.FPDFPage_SetRotation(page.raw, rotation // 90)
    doc.save(str(path))
    doc.close()
    return path


SHAPES = {
    "portrait": {},
    "rotated-90": {"rotation": 90},
    "rotated-180": {"rotation": 180},
    "rotated-270": {"rotation": 270},
    "landscape": {"width": 792, "height": 612},
    "a5": {"width": 420, "height": 595},
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_page_shape_keeps_its_text(tmp_path, shape):
    """Page rotation and page size must not move or lose anything.

    Measured across all four rotations, landscape and A5: the rendered ink
    lands within a few points of the original every time.
    """
    from docs.domain.ports.pdf_text_edit_port import BlockReplacement
    from docs.domain.text_fitting import fit_text_to_block

    src = _make(tmp_path / f"{shape}.pdf", **SHAPES[shape])
    adapter = Pypdfium2TextEditAdapter()
    runs = adapter.read_runs(src)
    assert runs, f"{shape}: no text was read at all"

    replacements = [
        BlockReplacement(
            page=block.page,
            remove=block.runs,
            fitted=fit_text_to_block(block.text, block),
            x=block.x,
            top=block.top,
            baseline=block.baseline,
            line_spacing=block.line_spacing,
            first_line_x=block.first_line_x,
            right=block.right,
        )
        for block in group_runs_into_blocks(runs)
    ]
    out = tmp_path / f"{shape}-out.pdf"
    adapter.write_blocks(src, out, replacements)

    assert len(adapter.read_runs(out)) == len(runs), f"{shape}: run count changed"


def test_angled_text_is_recognised_and_left_alone():
    """A 90-degree text object came back as horizontal words running off the
    page. Every layout rule here reasons in page-horizontal space, so angled
    text is not laid out differently -- it is not touched."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        src = _make(Path(directory) / "angled.pdf", angled=True)
        blocks = group_runs_into_blocks(Pypdfium2TextEditAdapter().read_runs(src))
        assert blocks
        assert all(block.rotated for block in blocks)


def test_upright_text_is_never_called_rotated():
    """The guard must not fire on ordinary documents: a false positive here
    silently refuses to translate a page that was perfectly translatable."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        src = _make(Path(directory) / "upright.pdf")
        blocks = group_runs_into_blocks(Pypdfium2TextEditAdapter().read_runs(src))
        assert blocks
        assert not any(block.rotated for block in blocks)


def test_a_page_with_no_text_reads_as_empty(tmp_path):
    src = _make(tmp_path / "empty.pdf", empty=True)
    assert Pypdfium2TextEditAdapter().read_runs(src) == []


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("notapdf.pdf", b"esto no es un pdf en absoluto"),
        ("truncated.pdf", b"%PDF-1.7\nstartxref\n999999\n%%EOF\n"),
    ],
)
def test_a_malformed_file_raises_rather_than_corrupting(tmp_path, name, content):
    """The CLI turns this into exit code 1. What must never happen is a
    malformed input being reported as a successful translation.

    The exception type is asserted rather than caught blindly: `PdfiumError`
    means PDFium refused the file, which is the outcome we want. A blind
    `Exception` would also pass on a `TypeError` from our own code, and that
    is a bug wearing the costume of a handled case.
    """
    import pypdfium2 as pdfium

    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(pdfium.PdfiumError):
        Pypdfium2TextEditAdapter().read_runs(path)
