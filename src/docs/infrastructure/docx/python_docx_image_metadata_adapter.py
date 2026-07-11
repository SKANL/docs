# src/docs/infrastructure/docx/python_docx_image_metadata_adapter.py
from __future__ import annotations

from pathlib import Path

from docx.image.exceptions import InvalidImageStreamError, UnrecognizedImageError
from docx.image.image import Image


class PythonDocxImageMetadataAdapter:
    """`ImageMetadataPort` implementation using python-docx's bundled,
    PIL-free image header parser (`docx.image`, design.md Decision 6b) --
    no new runtime dependency. Covers PNG/JPEG/GIF/BMP/TIFF."""

    def read_dimensions(self, path: Path) -> tuple[int, int] | None:
        try:
            image = Image.from_file(str(path))
        except (UnrecognizedImageError, InvalidImageStreamError, OSError):
            return None
        return image.px_width, image.px_height
