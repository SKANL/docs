from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class AtomicFilePort(Protocol):
    """Port for atomic file replacement owned by infrastructure."""

    def scratch_dir(self, parent: Path) -> AbstractContextManager[Path]: ...

    def atomic_finalize(self, source: Path, destination: Path) -> None: ...
