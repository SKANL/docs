import pytest
from PIL import Image

from docs.domain.visual_similarity import page_similarity

# A COLLAPSE floor, not a fidelity gate, and the difference is the whole
# point. Measured on one real document: the layout-DESTROYED output scored
# 0.8015 and the CORRECT translation 0.8253. A 0.02 margin cannot gate
# anything, and a denser or sparser page moves both numbers together -- the
# same correct translation of a small figure scores 0.60. Any threshold
# between those samples would be fitted to them, not derived from anything.
#
# So this asserts only what it can: the page did not collapse entirely (a
# wholly different page scores below 0.5, pinned by its own test above). The
# invariants that actually matter are exact and structural -- page count, page
# geometry, and every non-text object preserved -- and they are asserted in
# `test_pypdfium2_text_edit_adapter.py`, where they can be proven.
VISUAL_COLLAPSE_FLOOR = 0.5


def _png(tmp_path, name, box=None, color=(0, 0, 0)):
    image = Image.new("RGB", (200, 200), "white")
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                image.putpixel((x, y), color)
    path = tmp_path / name
    image.save(path)
    return path


def test_identical_pages_score_one(tmp_path):
    a = _png(tmp_path, "a.png", (10, 10, 50, 50))
    b = _png(tmp_path, "b.png", (10, 10, 50, 50))
    assert page_similarity(a, b) == pytest.approx(1.0)


def test_a_small_text_change_stays_above_the_floor(tmp_path):
    a = _png(tmp_path, "a.png", (10, 10, 50, 50))
    b = _png(tmp_path, "b.png", (10, 10, 58, 50))
    assert page_similarity(a, b) > VISUAL_COLLAPSE_FLOOR


def test_a_wholly_different_page_scores_low(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 200, 200))
    b = _png(tmp_path, "b.png", (0, 0, 1, 1))
    assert page_similarity(a, b) < 0.5


def test_differently_sized_pages_score_zero(tmp_path):
    a = _png(tmp_path, "a.png", (10, 10, 50, 50))
    b = tmp_path / "b.png"
    Image.new("RGB", (100, 100), "white").save(b)
    assert page_similarity(a, b) == 0.0


def test_a_translated_pdf_stays_visually_close_to_its_original(tmp_path):
    """The headline promise of this capability, as a number CI can fail on."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    from docs.domain.block_grouping import group_runs_into_blocks
    from docs.domain.ports.pdf_text_edit_port import BlockReplacement
    from docs.domain.text_fitting import fit_text_to_block
    from docs.infrastructure.pdf.pdfium2_pdf_render_adapter import Pdfium2PdfRenderAdapter
    from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import Pypdfium2TextEditAdapter

    figure = plt.figure(figsize=(6, 4))
    figure.text(0.1, 0.8, "Hello world", fontsize=18)
    figure.text(0.1, 0.5, "Second line of text", fontsize=12)
    original = tmp_path / "original.pdf"
    figure.savefig(original)
    plt.close(figure)

    editor = Pypdfium2TextEditAdapter()
    mapping = {
        "Hello world": "Hola mundo",
        "Second line of text": "Segunda linea de texto",
    }
    replacements = [
        BlockReplacement(
            page=block.page,
            remove=block.runs,
            fitted=fit_text_to_block(mapping.get(block.text, block.text), block),
            x=block.x,
            top=block.top,
        )
        for block in group_runs_into_blocks(editor.read_runs(original))
    ]
    translated = tmp_path / "translated.pdf"
    editor.write_blocks(original, translated, replacements)

    renderer = Pdfium2PdfRenderAdapter()
    before = renderer.render_pages(original, tmp_path / "before", autotrim=False)
    after = renderer.render_pages(translated, tmp_path / "after", autotrim=False)
    assert len(before) == len(after), "page count changed"
    score = page_similarity(before[0], after[0])
    assert score >= VISUAL_COLLAPSE_FLOOR, f"layout collapsed (score {score:.4f})"
