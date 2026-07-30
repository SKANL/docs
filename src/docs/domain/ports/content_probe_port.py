# src/docs/domain/ports/content_probe_port.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ContentSignals:
    """Content-probe output -- strings/flags only, zero I/O in the consumer
    (design.md ADR-D: "Signals-as-strings boundary"). Minimal PR1 surface:
    `extension` only, feeding item E's manual auto-detect. Item D (PR4)
    extends this with `pdf_title`/`first_headings`/`head_keywords` for full
    content-based source classification -- extend, never recreate."""

    extension: str = ""


class ContentProbePort(Protocol):
    def probe(self, path: Path) -> ContentSignals:
        """Reads content signals for `path`. MUST fail open: any read
        error returns an empty `ContentSignals`, never raises (design.md
        §4 "probe failures -> empty signals, fail-open" -- locale/platform
        read risk)."""
        ...
