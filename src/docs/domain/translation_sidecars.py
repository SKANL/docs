"""Where a translation keeps its memory and pending-slot file: beside the output document."""

from __future__ import annotations

from pathlib import Path

MEMORY_DIRNAME = "translations"
PENDING_SUFFIX = ".pending.json"


def translation_sidecars(destination: Path) -> tuple[Path, Path]:
    """`(memory_dir, pending_file)` for a translated output path."""
    return destination.parent / MEMORY_DIRNAME, destination.with_suffix(destination.suffix + PENDING_SUFFIX)
