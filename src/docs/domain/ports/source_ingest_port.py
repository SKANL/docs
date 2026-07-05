from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceIngestPort(Protocol):
    def ingest(self, src: Path, out_dir: Path) -> Path:
        """Convert `src` into a deterministic Markdown file under `out_dir`
        and return its path (document-ingest spec: `Type-Based Ingest
        Routing`)."""
        ...
