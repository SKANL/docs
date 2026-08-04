# src/docs/domain/ports/svg_rasterizer_port.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SvgRasterizerPort(Protocol):
    def rasterize(self, svg_path: Path, png_path: Path) -> None:
        """Rasterizes `svg_path` to `png_path` (design.md: "resvg + dims
        behind ports, optional-toolchain guarded"). Raises `RuntimeError`
        when the underlying toolchain is absent -- callers WARN+skip."""
        ...
