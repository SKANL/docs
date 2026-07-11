# tests/integration/test_image_metadata_adapter.py
"""`PythonDocxImageMetadataAdapter` (design.md Decision 6b): reads image
dimensions via python-docx's bundled, PIL-free `docx.image` parser -- no
new dependency. Unparseable content returns `None`, NEVER guessed or
raised (spec: asset-management "Deterministic Figure Catalog")."""
from __future__ import annotations

import base64
from pathlib import Path

from docs.infrastructure.docx.python_docx_image_metadata_adapter import (
    PythonDocxImageMetadataAdapter,
)

# 1x1 pixel PNG, same fixture already used in test_ingest_determinism.py.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def test_read_dimensions_of_a_real_png(tmp_path: Path):
    path = tmp_path / "pixel.png"
    path.write_bytes(_PIXEL_PNG)
    adapter = PythonDocxImageMetadataAdapter()

    dimensions = adapter.read_dimensions(path)

    assert dimensions == (1, 1)


def test_unparseable_file_returns_none_never_raises(tmp_path: Path):
    path = tmp_path / "not-an-image.png"
    path.write_bytes(b"this is not a real png file")
    adapter = PythonDocxImageMetadataAdapter()

    assert adapter.read_dimensions(path) is None


def test_missing_file_returns_none_never_raises(tmp_path: Path):
    adapter = PythonDocxImageMetadataAdapter()
    assert adapter.read_dimensions(tmp_path / "missing.png") is None
