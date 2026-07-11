# src/docs/domain/ports/image_metadata_port.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImageMetadataPort(Protocol):
    def read_dimensions(self, path: Path) -> tuple[int, int] | None:
        """Returns `(width_px, height_px)`, or `None` if `path` is missing
        or its content is not a parseable image -- NEVER guessed
        (design.md Decision 6b: determinism preserved)."""
        ...
