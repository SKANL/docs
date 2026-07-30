# tests/unit/infrastructure/test_pdfium2_pdf_render_adapter.py
"""`PdfRenderPort` implementation via `pypdfium2`: render PDF pages to
deterministic PNGs so figures can be pulled from vector-only source PDFs
(no embedded raster to extract)."""
from pathlib import Path

from PIL import Image

from docs.infrastructure.pdf.pdfium2_pdf_render_adapter import Pdfium2PdfRenderAdapter


def _make_pdf(path: Path, pages: int) -> None:
    """Write a tiny multi-page PDF fixture (one solid-color image per page)."""
    colors = [(220, 40, 40), (40, 120, 220), (40, 200, 90)]
    images = [Image.new("RGB", (120, 160), colors[i % len(colors)]) for i in range(pages)]
    images[0].save(path, save_all=True, append_images=images[1:])


def test_render_pages_writes_one_png_per_page(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, 2)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = Pdfium2PdfRenderAdapter().render_pages(pdf, out_dir)

    assert [p.name for p in written] == ["sample-p01.png", "sample-p02.png"]
    for png in written:
        assert png.exists() and png.stat().st_size > 0
        with Image.open(png) as img:
            assert img.format == "PNG"
            assert img.size[0] > 0 and img.size[1] > 0


def test_pages_spec_selects_a_subset(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, 3)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = Pdfium2PdfRenderAdapter().render_pages(pdf, out_dir, pages="1,3")

    assert [p.name for p in written] == ["sample-p01.png", "sample-p03.png"]
    assert not (out_dir / "sample-p02.png").exists()


def test_single_page_spec_writes_exactly_one_png(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, 2)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = Pdfium2PdfRenderAdapter().render_pages(pdf, out_dir, pages="1")

    assert [p.name for p in written] == ["sample-p01.png"]


def test_range_spec_expands_and_dedupes_in_page_order(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, 3)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    written = Pdfium2PdfRenderAdapter().render_pages(pdf, out_dir, pages="2-3,2")

    assert [p.name for p in written] == ["sample-p02.png", "sample-p03.png"]


def test_autotrim_crops_surrounding_whitespace(tmp_path: Path):
    # A page that is mostly white with a small centered block must trim
    # down to roughly the block (+ padding), far smaller than the full page.
    pdf = tmp_path / "boxed.pdf"
    page = Image.new("RGB", (400, 400), (255, 255, 255))
    for x in range(180, 220):
        for y in range(180, 220):
            page.putpixel((x, y), (0, 0, 0))
    page.save(pdf)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    [trimmed] = Pdfium2PdfRenderAdapter().render_pages(pdf, out_dir, dpi=72, autotrim=True)
    [full] = Pdfium2PdfRenderAdapter().render_pages(pdf, tmp_path / "full", dpi=72, autotrim=False)

    with Image.open(trimmed) as t, Image.open(full) as f:
        assert t.size[0] < f.size[0]
        assert t.size[1] < f.size[1]


def test_rerender_is_byte_identical(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, 1)

    first = Pdfium2PdfRenderAdapter().render_pages(pdf, tmp_path / "a")
    second = Pdfium2PdfRenderAdapter().render_pages(pdf, tmp_path / "b")

    assert first[0].read_bytes() == second[0].read_bytes()
