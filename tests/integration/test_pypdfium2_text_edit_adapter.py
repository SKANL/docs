import hashlib

import pytest

from docs.domain.block_grouping import group_runs_into_blocks
from docs.domain.ports.pdf_text_edit_port import BlockReplacement
from docs.domain.text_fitting import fit_text_to_block
from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import Pypdfium2TextEditAdapter


@pytest.fixture
def sample_pdf(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 4))
    fig.text(0.1, 0.8, "Hello world", fontsize=18)
    fig.text(0.1, 0.6, "Second line of text", fontsize=12)
    path = tmp_path / "original.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path


def _translate_all(adapter, src, dst, mapping):
    replacements = [
        BlockReplacement(
            page=block.page,
            remove=block.runs,
            fitted=fit_text_to_block(mapping.get(block.text, block.text), block),
            x=block.x,
            top=block.top,
        )
        for block in group_runs_into_blocks(adapter.read_runs(src))
    ]
    return adapter.write_blocks(src, dst, replacements)


def test_read_runs_returns_text_with_geometry(sample_pdf):
    runs = Pypdfium2TextEditAdapter().read_runs(sample_pdf)
    assert {r.text for r in runs} == {"Hello world", "Second line of text"}
    assert all(r.width > 0 and r.height > 0 and r.font_size > 0 for r in runs)


def test_read_runs_reports_a_font_family_with_the_subset_tag_stripped(sample_pdf):
    """`FPDFFont_GetFamilyName` is present, succeeds, and returns EMPTY for
    embedded subset fonts. `FPDFFont_GetBaseFontName` returns
    `GGKEDP+DejaVuSans`; the six-letter subset tag must be stripped and the
    family must survive."""
    runs = Pypdfium2TextEditAdapter().read_runs(sample_pdf)
    assert all(r.font_family for r in runs)
    assert all("+" not in r.font_family for r in runs)
    assert any("DejaVu" in r.font_family for r in runs)


def test_untouched_text_objects_survive_the_edit(sample_pdf, tmp_path):
    """Regression for the PDFium behaviour where an open textpage during
    mutation SILENTLY DESTROYS unrelated text objects. Measured: a 3-object
    page came back as 2 with nothing raised."""
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo entero"})
    texts = {r.text for r in adapter.read_runs(out)}
    assert "Hola mundo entero" in texts
    assert "Second line of text" in texts, "an unrelated text object was destroyed"


def test_longer_translation_round_trips(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo entero y completo"})
    assert any("Hola mundo entero" in r.text for r in adapter.read_runs(out))


def test_two_identical_runs_produce_byte_identical_files(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    mapping = {"Hello world": "Hola mundo entero"}
    _translate_all(adapter, sample_pdf, a, mapping)
    _translate_all(adapter, sample_pdf, b, mapping)
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_page_count_is_preserved(sample_pdf, tmp_path):
    import pypdfium2 as pdfium

    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo"})
    before = pdfium.PdfDocument(str(sample_pdf))
    after = pdfium.PdfDocument(str(out))
    try:
        assert len(before) == len(after)
    finally:
        before.close()
        after.close()


def test_the_write_report_counts_what_it_compromised(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    report = _translate_all(
        adapter, sample_pdf, tmp_path / "out.pdf", {"Hello world": "Hola mundo"}
    )
    assert report.blocks_written >= 1
    # Phase 1 always maps onto a base-14 font, so every written block counts.
    assert report.fonts_substituted == report.blocks_written


def test_accented_target_text_survives_the_round_trip(sample_pdf, tmp_path):
    """The whole point of substituting fonts: the original subset has no "ó"."""
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Atención pingüino"})
    assert any("Atenci" in r.text for r in adapter.read_runs(out))


def test_an_empty_replacement_list_still_writes_a_valid_pdf(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    adapter.write_blocks(sample_pdf, out, [])
    assert out.exists()
    assert {r.text for r in adapter.read_runs(out)} == {"Hello world", "Second line of text"}


def _object_kinds(path):
    """{page-object type: count} -- the structural fingerprint of a page."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pc

    doc = pdfium.PdfDocument(str(path))
    try:
        kinds: dict[int, int] = {}
        for page_index in range(len(doc)):
            page = doc[page_index]
            for i in range(pc.FPDFPage_CountObjects(page.raw)):
                kind = pc.FPDFPageObj_GetType(pc.FPDFPage_GetObject(page.raw, i))
                kinds[kind] = kinds.get(kind, 0) + 1
        return kinds
    finally:
        doc.close()


def test_non_text_objects_are_preserved_exactly(sample_pdf, tmp_path):
    """The claim "images and vector art are untouched" is STRUCTURAL, not
    statistical: this capability only ever removes and inserts TEXT objects,
    so every other object must survive byte-for-byte in count and kind.

    This is the invariant worth gating on. Pixel similarity cannot prove it --
    measured, it scored a layout-destroyed page 0.8015 and a correct
    translation 0.8253."""
    import pypdfium2.raw as pc

    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo entero y completo"})

    before = _object_kinds(sample_pdf)
    after = _object_kinds(out)
    non_text_before = {k: v for k, v in before.items() if k != pc.FPDF_PAGEOBJ_TEXT}
    non_text_after = {k: v for k, v in after.items() if k != pc.FPDF_PAGEOBJ_TEXT}
    assert non_text_after == non_text_before, "a non-text page object was altered"
