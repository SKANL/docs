"""Application services for explicit visual baseline management."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class VisualBaselineError(ValueError):
    """Raised when a baseline cannot be safely prepared or published."""


class VisualBaselineService:
    """Promote rendered PNG previews to an explicit, atomic baseline."""

    def update(self, source_dir: Path, destination_dir: Path, *, overwrite: bool = False) -> tuple[Path, ...]:
        source_dir = source_dir.resolve()
        destination_dir = destination_dir.resolve()
        if not source_dir.is_dir():
            raise VisualBaselineError(f"visual preview directory does not exist: {source_dir}")
        previews = tuple(sorted(source_dir.glob("*.png"), key=lambda path: path.name))
        if not previews:
            raise VisualBaselineError(f"visual preview directory contains no PNG pages: {source_dir}")
        for preview in previews:
            try:
                with Image.open(preview) as image:
                    image.verify()
                    if image.width <= 0 or image.height <= 0:
                        raise VisualBaselineError(f"visual preview has invalid dimensions: {preview.name}")
            except (OSError, UnidentifiedImageError) as exc:
                raise VisualBaselineError(f"visual preview is unreadable: {preview.name}: {exc}") from exc
        if destination_dir.exists() and not overwrite:
            raise VisualBaselineError(f"visual baseline already exists; pass --update: {destination_dir}")
        destination_dir.parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f".{destination_dir.name}.", dir=destination_dir.parent))
        backup: Path | None = None
        try:
            for preview in previews:
                shutil.copyfile(preview, scratch / preview.name)
            if destination_dir.exists():
                backup = destination_dir.with_name(f".{destination_dir.name}.previous")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(destination_dir, backup)
            try:
                os.replace(scratch, destination_dir)
            except OSError:
                if backup is not None and backup.exists() and not destination_dir.exists():
                    os.replace(backup, destination_dir)
                raise
            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            return tuple(destination_dir / preview.name for preview in previews)
        except OSError as exc:
            raise VisualBaselineError(f"could not publish visual baseline: {exc}") from exc
        finally:
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)
            if backup is not None and backup.exists() and destination_dir.exists():
                shutil.rmtree(backup, ignore_errors=True)
