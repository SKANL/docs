# src/docs/infrastructure/visuals/resvg_rasterizer_adapter.py
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.process_policy import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS


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
        png_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{png_path.stem}-", suffix=png_path.suffix, dir=png_path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with open(descriptor, "wb", closefd=True):
                pass
            args = [resvg, str(svg_path), str(temporary_path)]
            if self.font_dir is not None:
                args += ["--use-fonts-dir", str(self.font_dir)]
            subprocess.run(args, check=True, timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS)
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise RuntimeError("resvg produced an empty PNG")
            temporary_path.replace(png_path)
        finally:
            temporary_path.unlink(missing_ok=True)
