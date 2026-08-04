# src/docs/infrastructure/visuals/resvg_rasterizer_adapter.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from docs.domain.ports.tool_resolver_port import ToolResolverPort


class ResvgRasterizerAdapter:
    """`SvgRasterizerPort` implementation using the `resvg` subprocess.

    Threat Matrix "Subprocess arg composition": `svg_path`/`png_path` are
    passed as explicit, fixed argv entries via `subprocess.run([...],
    check=True)` -- never `shell=True`, never string-interpolated. Absent
    `resvg` (optional PATH toolchain, mirrors `MermaidSvgRenderer`) raises a
    clean, catchable `RuntimeError` so the generate-visuals stage (Slice 5)
    can WARN+skip it -- never crashes `Deps()` construction.

    `font_dir` pins `--use-fonts-dir` for determinism (design.md: "pinned
    font-dir"); no font is vendored by this repo yet (design.md Open
    Questions), so it defaults to `None` and the flag is simply omitted."""

    def __init__(
        self,
        tool_resolver: ToolResolverPort,
        paths: dict[str, Any] | None = None,
        font_dir: Path | None = None,
    ) -> None:
        self.tool_resolver = tool_resolver
        self.paths = paths or {}
        self.font_dir = Path(font_dir) if font_dir else None

    def rasterize(self, svg_path: Path, png_path: Path) -> None:
        resvg = self.tool_resolver.resolve_resvg(self.paths)
        if not resvg:
            raise RuntimeError(
                "resvg no está disponible en PATH. Instálalo desde "
                "https://github.com/linebender/resvg para rasterizar diagramas SVG a PNG."
            )
        args = [resvg, str(svg_path), str(png_path)]
        if self.font_dir is not None:
            args += ["--use-fonts-dir", str(self.font_dir)]
        subprocess.run(args, check=True)
