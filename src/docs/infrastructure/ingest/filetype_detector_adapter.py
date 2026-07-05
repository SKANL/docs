# src/docs/infrastructure/ingest/filetype_detector_adapter.py
from __future__ import annotations

from pathlib import Path

import filetype

# Plain-text formats have no distinguishing magic bytes, so `filetype.guess`
# returns None for them; fall back to extension matching (document-ingest
# spec: `File-Type Detection` scenario "Fallback to extension for text formats").
_EXTENSION_FALLBACK: dict[str, str] = {
    ".md": "md",
    ".txt": "txt",
}


class FiletypeDetectorAdapter:
    """Detects a source file's type via magic-byte sniffing (`filetype` lib),
    falling back to file extension for formats with no distinguishing
    signature (md/txt). Returns "" when neither method resolves the type —
    never raises (document-ingest spec: `File-Type Detection`)."""

    def detect(self, path: Path) -> str:
        guess = filetype.guess(str(path))
        if guess is not None:
            return guess.extension
        return _EXTENSION_FALLBACK.get(path.suffix.lower(), "")
