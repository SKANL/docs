# src/docs/infrastructure/ingest/content_probe_adapter.py
from __future__ import annotations

from pathlib import Path

from docs.domain.ports.content_probe_port import ContentSignals


class FilesystemContentProbeAdapter:
    """`ContentProbePort` implementation, minimal PR1 surface (item E's
    manual auto-detect): the file extension only. PR4 (item D) extends this
    with PDF title/heading/keyword extraction for content classification --
    same adapter, more signals, never a second port.

    Fail-open (design.md §4): any read failure returns an empty
    `ContentSignals` instead of raising, so a single unreadable file never
    breaks a doctor run or an ingest walk."""

    def probe(self, path: Path) -> ContentSignals:
        try:
            extension = path.suffix.lower().lstrip(".")
        except (OSError, ValueError):
            return ContentSignals()
        return ContentSignals(extension=extension)
