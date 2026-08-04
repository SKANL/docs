# tests/integration/test_resvg_rasterizer_adapter_integration.py
"""Real-toolchain integration check of `ResvgRasterizerAdapter` (same code
path as `tests/unit/infrastructure/test_resvg_rasterizer_adapter.py`,
exercised against an actual `resvg` installation). Skips cleanly when
`resvg` is absent from PATH (mirrors the `mmdc`/`pandoc`/`java`/`libreoffice`
skipif precedent). PNG dims are read via the EXISTING `ImageMetadataPort`
(design.md: "reuses existing ImageMetadataPort.read_dimensions -- no new
dims port")."""
from __future__ import annotations

import shutil

import pytest

from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter

_HAS_RESVG = shutil.which("resvg") is not None

_FIXTURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="32">'
    '<rect width="64" height="32" fill="red"/></svg>'
)


@pytest.mark.skipif(not _HAS_RESVG, reason="resvg not installed")
def test_rasterize_svg_to_png_with_dims(tmp_path):
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text(_FIXTURE_SVG, encoding="utf-8")
    png_path = tmp_path / "diagram.png"
    adapter = ResvgRasterizerAdapter(SystemToolResolverAdapter())

    adapter.rasterize(svg_path, png_path)

    dims = PythonDocxImageMetadataAdapter().read_dimensions(png_path)
    assert dims is not None
    width_px, height_px = dims
    assert width_px is not None
    assert height_px is not None


@pytest.mark.skipif(not _HAS_RESVG, reason="resvg not installed")
def test_rasterize_same_svg_twice_is_byte_identical(tmp_path):
    svg_path = tmp_path / "diagram.svg"
    svg_path.write_text(_FIXTURE_SVG, encoding="utf-8")
    adapter = ResvgRasterizerAdapter(SystemToolResolverAdapter())

    png_a = tmp_path / "a.png"
    png_b = tmp_path / "b.png"
    adapter.rasterize(svg_path, png_a)
    adapter.rasterize(svg_path, png_b)

    assert png_a.read_bytes() == png_b.read_bytes()
