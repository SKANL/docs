# src/docs/infrastructure/visuals/mermaid_svg_renderer.py
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.infrastructure.ingest.atomic_ingest_write import scratch_dir


class MermaidSvgRenderer:
    """`VisualRendererPort` implementation for `type = "mermaid"`: renders
    `spec.source` (raw Mermaid diagram text) via the `mmdc` (mermaid-cli)
    subprocess to SVG text.

    Threat Matrix "Subprocess arg composition": `spec.source` is
    agent-authored and NEVER passed as a shell argument -- it is written to a
    temp `.mmd` file under `scratch_dir` (same precedent as
    `pandoc_ingest_adapter.py`) and `mmdc` is invoked with a FIXED arg list
    via `subprocess.run([...], check=True)`, never `shell=True`. Absent
    `mmdc` (optional toolchain, mirrors `pandoc_ingest_adapter.py`'s
    `RuntimeError`) or a failing conversion raises a clean, catchable error
    so the generate-visuals stage (Slice 5) can WARN+skip it -- never crashes
    `Deps()` construction."""

    type = "mermaid"

    def __init__(
        self,
        tool_resolver: ToolResolverPort,
        paths: dict[str, Any] | None = None,
        scratch_root: Path | None = None,
    ) -> None:
        self.tool_resolver = tool_resolver
        self.paths = paths or {}
        # No document-root context at this layer (`render` takes only a
        # `VisualSpec`), so the scratch dir defaults to the system temp dir
        # rather than a per-document `out_dir` -- the mermaid source only
        # ever lives here transiently, never written to a final destination
        # by this renderer.
        self.scratch_root = Path(scratch_root) if scratch_root else Path(tempfile.gettempdir())

    def render(self, spec: VisualSpec) -> str:
        mmdc = self.tool_resolver.resolve_mmdc(self.paths)
        if not mmdc:
            raise RuntimeError(
                "mmdc (mermaid-cli) no está disponible en PATH. Instálalo con "
                "`npm install -g @mermaid-js/mermaid-cli` para generar diagramas mermaid."
            )
        with scratch_dir(self.scratch_root) as tmp_dir:
            tmp_mmd = tmp_dir / "diagram.mmd"
            tmp_svg = tmp_dir / "diagram.svg"
            tmp_mmd.write_text(spec.source, encoding="utf-8")
            subprocess.run(
                [mmdc, "-i", str(tmp_mmd), "-o", str(tmp_svg), "--outputFormat", "svg"],
                check=True,
            )
            return tmp_svg.read_text(encoding="utf-8")
