# tests/unit/domain/test_svg_rasterizer_port.py
"""`SvgRasterizerPort` (design.md "resvg + dims behind ports") -- the pure
contract shape a concrete resvg CLI adapter implements. No I/O here."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from docs.domain.ports.svg_rasterizer_port import SvgRasterizerPort


def test_svg_rasterizer_port_is_a_protocol():
    assert issubclass(SvgRasterizerPort, Protocol)  # type: ignore[arg-type]


def test_svg_rasterizer_port_declares_rasterize():
    @runtime_checkable
    class _Checkable(SvgRasterizerPort, Protocol):  # type: ignore[misc]
        ...

    class FakeRasterizer:
        def rasterize(self, svg_path: Path, png_path: Path) -> None:
            return None

    assert isinstance(FakeRasterizer(), _Checkable)
