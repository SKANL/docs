# src/docs/infrastructure/visuals/mermaid_svg_renderer.py
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.ports.visual_renderer_port import VisualSpec
from docs.domain.process_policy import DEFAULT_SUBPROCESS_TIMEOUT_SECONDS
from docs.domain.svg_normalize import ensure_accessibility_metadata
from docs.infrastructure.ingest.atomic_ingest_write import scratch_dir

_MAX_SOURCE_LENGTH = 1_000_000
_MAX_OUTPUT_LENGTH = 4_000_000


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
        if len(spec.source) > _MAX_SOURCE_LENGTH:
            raise ValueError(f"Mermaid source exceeds {_MAX_SOURCE_LENGTH} characters.")
        if not spec.decorative and not spec.semantic_summary.strip() and not spec.data_fallback.strip():
            print(
                f"WARN: el diagrama mermaid '{spec.label}' no tiene resumen semántico ni alternativa de datos; "
                "su accesibilidad depende de la semántica emitida por mmdc.",
                file=sys.stderr,
            )
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
            try:
                subprocess.run(
                    [mmdc, "-i", str(tmp_mmd), "-o", str(tmp_svg), "--outputFormat", "svg"],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
                )
            except subprocess.CalledProcessError as exc:
                # A raw CalledProcessError reads as `Command '[...long paths...]'
                # returned non-zero exit status 1` -- and mmdc's real diagnostic
                # went to an uncaptured stderr. The generate-visuals stage
                # surfaces this as `WARN: {exc}` to the author, so the message
                # has to say what is wrong with THEIR diagram.
                detail = (exc.stderr or exc.stdout or "").strip()
                raise RuntimeError(
                    f"mmdc no pudo renderizar el diagrama «{spec.label}»." + (f" Detalle:\n{detail}" if detail else "")
                ) from exc
            if tmp_svg.stat().st_size > _MAX_OUTPUT_LENGTH:
                raise ValueError(f"Mermaid SVG output exceeds {_MAX_OUTPUT_LENGTH} bytes.")
            svg_text = tmp_svg.read_text(encoding="utf-8")
            if len(svg_text) > _MAX_OUTPUT_LENGTH:
                raise ValueError(f"Mermaid SVG output exceeds {_MAX_OUTPUT_LENGTH} characters.")
            return ensure_accessibility_metadata(
                svg_text,
                spec.accessible_name,
                spec.accessible_description,
                decorative=spec.decorative,
            )
