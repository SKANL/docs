from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir


class AtomicFileAdapter:
    """Infrastructure adapter exposing the atomic file port."""

    def scratch_dir(self, parent: Path) -> AbstractContextManager[Path]:
        return scratch_dir(parent)

    def atomic_finalize(self, source: Path, destination: Path) -> None:
        atomic_finalize(source, destination)
