# tests/unit/application/test_html_render_svg_swap.py
"""HTML-only sibling `.png -> .svg` swap (tasks.md Slice 6, task 6.1;
design.md "HTML sibling-SVG swap" decision; document-render spec "HTML
Prefers Sibling SVG for a Bound Figure"). `html_render.build` swaps a bound
figure's resolved `.png` path for its same-stem, same-dir `.svg` sibling
when one exists on disk -- `docx_assembly.py` never sees this swap (proven
separately by `test_docx_assembly_ignores_sibling_svg.py`, task 6.2)."""
from __future__ import annotations

from docs.application.html_render import _prefer_sibling_svg
from docs.domain.figure_binding import BoundFigure


def _bound_figure(path: str) -> BoundFigure:
    return BoundFigure(
        label="organigrama",
        catalog_id="fig-abc12345",
        path=path,
        width_px=300,
        height_px=200,
        caption="Organigrama del equipo",
    )


def test_bound_figure_with_sibling_svg_swaps_to_svg_path(tmp_path):
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    png_path = figures_dir / "visual-abc12345.png"
    svg_path = figures_dir / "visual-abc12345.svg"
    png_path.write_bytes(b"fake-png-bytes")
    svg_path.write_text("<svg></svg>", encoding="utf-8")
    original = _bound_figure(str(png_path))

    swapped = _prefer_sibling_svg({"organigrama": original})

    result = swapped["organigrama"]
    assert result.path == str(svg_path)
    # Every other field is unchanged -- dims stay the PNG's dims so the
    # emitted `{width=Xin}` attribute is identical (design.md: "same dims").
    assert result.width_px == original.width_px
    assert result.height_px == original.height_px
    assert result.caption == original.caption
    assert result.label == original.label
    assert result.catalog_id == original.catalog_id


def test_bound_figure_without_sibling_svg_is_unaffected(tmp_path):
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    png_path = figures_dir / "fig-abc12345.png"
    png_path.write_bytes(b"fake-png-bytes")
    # No sibling `.svg` written -- regression guard for a plain ingested
    # photo, which never has one.
    original = _bound_figure(str(png_path))

    swapped = _prefer_sibling_svg({"organigrama": original})

    assert swapped["organigrama"] == original


def test_non_png_bound_figure_path_is_unaffected(tmp_path):
    # A bound figure that is already something other than `.png` (e.g. a
    # future format) is never touched by the swap.
    jpg_path = tmp_path / "fig-abc12345.jpg"
    jpg_path.write_bytes(b"fake-jpg-bytes")
    original = _bound_figure(str(jpg_path))

    swapped = _prefer_sibling_svg({"organigrama": original})

    assert swapped["organigrama"] == original
