from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceTypeDetectorPort(Protocol):
    def detect(self, path: Path) -> str:
        """Return the detected source kind id (e.g. "pdf", "docx", "md",
        "txt"), or "" when the type cannot be resolved by magic bytes or
        extension (document-ingest spec: `File-Type Detection`)."""
        ...
