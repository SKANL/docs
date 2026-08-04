# src/docs/domain/ports/visual_renderer_port.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VisualSpec:
    """Agent-authored declarative visual request (design.md: "chart spec is
    DECLARATIVE data, never executed code"). `source` is DATA only -- inline
    text or a JSON string -- never `eval`/`exec`'d by any renderer."""

    label: str
    type: str
    source: str
    caption: str = ""


class VisualRendererPort(Protocol):
    """Format-agnostic visual renderer contract, keyed by `type` (mirrors
    `ingest_handlers` keyed by `kind`). `render` returns RAW SVG text; the
    caller normalizes it via `domain/svg_normalize.py:normalize_svg` before
    hashing/writing (design.md Decision "normalize_svg lives in domain")."""

    type: str

    def render(self, spec: VisualSpec) -> str:
        """Renders `spec` to raw SVG text. Raises on malformed spec / absent
        toolchain -- callers (the generate-visuals stage) WARN+skip."""
        ...
