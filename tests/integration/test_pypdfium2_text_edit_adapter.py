import hashlib

import pytest

from docs.domain.block_grouping import group_runs_into_blocks
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, WriteDiagnostic
from docs.domain.text_fitting import FittedText, fit_text_to_block
from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import (
    Pypdfium2TextEditAdapter,
    _missing_expected_lines,
    _ObjectSnapshot,
)


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


def _replacement(block, text, *, x=None, top=None, baseline=None, right=None):
    return BlockReplacement(
        page=block.page,
        remove=block.runs,
        fitted=FittedText([text], block.font_size, False),
        x=block.x if x is None else x,
        top=block.top if top is None else top,
        baseline=block.baseline if baseline is None else baseline,
        right=block.right if right is None else right,
    )


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


def test_post_write_verification_accepts_a_contained_replacement(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    block = next(
        block
        for block in group_runs_into_blocks(adapter.read_runs(sample_pdf))
        if block.text == "Hello world"
    )

    report = adapter.write_blocks(
        sample_pdf,
        tmp_path / "contained.pdf",
        [_replacement(block, "Hi")],
    )

    assert report.verification_diagnostics == ()
    assert report.blocks_unsafe == 0


def test_post_write_verification_accepts_permitted_horizontal_expansion(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    block = next(
        block
        for block in group_runs_into_blocks(adapter.read_runs(sample_pdf))
        if block.text == "Hello world"
    )

    report = adapter.write_blocks(
        sample_pdf,
        tmp_path / "overflow.pdf",
        [_replacement(block, "This replacement may use the detected column", right=400.0)],
    )

    assert report.verification_diagnostics == ()


def test_post_write_verification_reports_clipping_outside_permitted_box(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    block = next(
        block
        for block in group_runs_into_blocks(adapter.read_runs(sample_pdf))
        if block.text == "Hello world"
    )

    report = adapter.write_blocks(
        sample_pdf,
        tmp_path / "clipped.pdf",
        [
            BlockReplacement(
                page=block.page,
                remove=block.runs,
                fitted=FittedText(["One", "Two", "Three"], block.font_size, False),
                x=block.x,
                top=block.top,
                baseline=block.baseline,
                right=block.right,
                line_spacing=block.font_size,
            )
        ],
    )

    assert [item.code for item in report.verification_diagnostics] == [
        "pdf.write.clipped"
    ]
    assert report.verification_diagnostics[0].page == 1
    assert report.blocks_unsafe == 1


def test_post_write_verification_reports_out_of_page_text(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    block = next(
        block
        for block in group_runs_into_blocks(adapter.read_runs(sample_pdf))
        if block.text == "Hello world"
    )

    report = adapter.write_blocks(
        sample_pdf,
        tmp_path / "clipped.pdf",
        [_replacement(block, "Clipped", x=-10.0, right=100.0)],
    )

    assert {item.code for item in report.verification_diagnostics} == {
        "pdf.write.outside_page_bounds",
    }


def test_post_write_verification_reports_overlap_with_untouched_text(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    blocks = {
        block.text: block for block in group_runs_into_blocks(adapter.read_runs(sample_pdf))
    }
    target = blocks["Hello world"]
    untouched = blocks["Second line of text"]

    report = adapter.write_blocks(
        sample_pdf,
        tmp_path / "overlap.pdf",
        [
            _replacement(
                target,
                "Overlap",
                x=untouched.x,
                top=untouched.top,
                baseline=untouched.baseline,
                right=untouched.right,
            )
        ],
    )

    overlap = [
        item
        for item in report.verification_diagnostics
        if item.code == "pdf.write.overlaps_untouched_object"
    ]
    assert len(overlap) == 1
    assert overlap[0].object_index is not None


def test_post_write_diagnostics_are_deterministic(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    blocks = group_runs_into_blocks(adapter.read_runs(sample_pdf))
    target = next(block for block in blocks if block.text == "Hello world")
    replacement = _replacement(target, "Clipped", x=-10.0, right=100.0)

    first = adapter.write_blocks(sample_pdf, tmp_path / "a.pdf", [replacement])
    second = adapter.write_blocks(sample_pdf, tmp_path / "b.pdf", [replacement])

    assert first.verification_diagnostics == second.verification_diagnostics
    assert first.verification_diagnostics == tuple(
        sorted(
            first.verification_diagnostics,
            key=lambda item: (
                item.page,
                item.replacement_index,
                item.code,
                item.object_index if item.object_index is not None else -1,
                item.bounds,
            ),
        )
    )


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


def test_pdf_verification_failure_does_not_publish_partial_output(sample_pdf, tmp_path, monkeypatch):
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    out.write_bytes(b"previous output")

    def fail_verification(_path, _specs):
        raise RuntimeError("verification failed")

    monkeypatch.setattr(adapter, "_verify_output", fail_verification)

    with pytest.raises(RuntimeError, match="verification failed"):
        adapter.write_blocks(sample_pdf, out, [])

    assert out.read_bytes() == b"previous output"


def test_missing_replacement_lines_prevent_publication(sample_pdf, tmp_path, monkeypatch):
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    out.write_bytes(b"previous output")
    missing = WriteDiagnostic(
        code="pdf.write.missing_replacement_lines",
        page=1,
        replacement_index=0,
        bounds=(0, 0, 10, 10),
        reference_bounds=(0, 0, 10, 10),
    )
    monkeypatch.setattr(adapter, "_verify_output", lambda _path, _specs: (missing,))

    with pytest.raises(RuntimeError, match="missing replacement lines"):
        adapter.write_blocks(sample_pdf, out, [])

    assert out.read_bytes() == b"previous output"


def test_missing_replacement_lines_are_reported_in_expected_order():
    expected = (
        _ObjectSnapshot(0, "first", (0, 0, 10, 10)),
        _ObjectSnapshot(1, "second", (0, 10, 10, 20)),
    )
    actual = (_ObjectSnapshot(4, "second", (0, 10, 10, 20)),)

    assert _missing_expected_lines(expected, actual) == (expected[0],)


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


def test_font_size_comes_from_the_text_matrix_not_the_bare_api(tmp_path):
    """`FPDFTextObj_GetFontSize` returns the UNSCALED size; real documents
    carry the true size in the text matrix.

    Measured on a 120-page book: every run reported 1.00 while its matrix held
    11, 13 or 14. Trusting the bare call redraws the whole document at one
    point — invisible text — and makes every width estimate in the fitter
    wrong by more than tenfold.

    A matplotlib fixture has an identity matrix and hides this completely,
    which is why this test builds a SCALED one by hand.
    """
    import ctypes

    import pypdfium2 as pdfium
    import pypdfium2.raw as pc

    doc = pdfium.PdfDocument.new()
    page = doc.new_page(300, 200)
    font = pc.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    obj = pc.FPDFPageObj_CreateTextObj(doc.raw, font, 1.0)  # size 1 ...
    buf = ctypes.create_string_buffer("Escalado".encode("utf-16-le") + b"\x00\x00")
    pc.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)))
    pc.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
    pc.FPDFPageObj_Transform(obj, 14, 0, 0, 14, 20, 100)  # ... scaled x14
    pc.FPDFPage_InsertObject(page.raw, obj)
    pc.FPDFPage_GenerateContent(page.raw)
    scaled = tmp_path / "scaled.pdf"
    doc.save(str(scaled))
    doc.close()

    runs = Pypdfium2TextEditAdapter().read_runs(scaled)
    assert runs, "the scaled fixture produced no readable run"
    assert runs[0].font_size == pytest.approx(14.0, abs=0.5), (
        f"expected the matrix-scaled 14pt, got {runs[0].font_size} "
        "(1.0 means the bare API value leaked through)"
    )


def test_no_word_is_lost_from_the_output_text_layer(tmp_path):
    """A translated PDF must remain a usable DOCUMENT, not just a picture of
    one: copy, search and screen readers all read the text layer.

    Justifying by repositioning each word broke exactly this. PDFium infers
    word boundaries from the DISTANCE between text objects, so words placed a
    fraction of a point apart came back joined --
    `"Excuseme!Doesanyonehereknow..."`. The pages looked right; 217 words
    across a real book were unreadable to anything but an eye. Justifying by
    stretching one object, whose spaces are real characters, cannot do that.
    """
    import re

    import pypdfium2 as pdfium

    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(6, 4))
    sentence = "Excuse me does anyone here know anyone who works at a big firm"
    figure.text(0.1, 0.8, sentence, fontsize=9)
    figure.text(0.1, 0.6, "Second line with several separate words", fontsize=9)
    src = tmp_path / "words.pdf"
    figure.savefig(src)
    plt.close(figure)

    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, src, out, {})

    def words(path):
        doc = pdfium.PdfDocument(str(path))
        try:
            text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        finally:
            doc.close()
        return set(re.findall(r"\w+", text.lower()))

    missing = words(src) - words(out)
    assert not missing, f"the output text layer lost words: {sorted(missing)}"
