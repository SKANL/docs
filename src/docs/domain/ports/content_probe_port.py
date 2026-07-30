# src/docs/domain/ports/content_probe_port.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ContentSignals:
    """Content-probe output -- strings/flags only, zero I/O in the consumer
    (design.md ADR-D: "Signals-as-strings boundary"). PR1 surface:
    `extension`, feeding item E's manual auto-detect. PR4 (item D) adds
    `pdf_title`/`first_headings`/`head_keywords` for full content-based
    source classification -- raw, case-folded strings only; the domain
    classifier (never the adapter) owns lexicon matching and accent
    folding, keeping the adapter role-agnostic."""

    extension: str = ""
    pdf_title: str = ""
    first_headings: tuple[str, ...] = ()
    head_keywords: tuple[str, ...] = ()


class ContentProbePort(Protocol):
    def probe(self, path: Path) -> ContentSignals:
        """Reads content signals for `path`. MUST fail open: any read
        error returns an empty `ContentSignals`, never raises (design.md
        §4 "probe failures -> empty signals, fail-open" -- locale/platform
        read risk)."""
        ...
