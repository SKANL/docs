import base64
from pathlib import Path

import pytest

from docs.application.imports import ImportError, SourceImportService


def test_import_writes_hashed_source_atomically(tmp_path: Path) -> None:
    result = SourceImportService().import_base64(
        tmp_path, "source.pdf", base64.b64encode(b"pdf-content").decode()
    )
    destination = Path(result["path"])
    assert destination.is_file()
    assert destination.read_bytes() == b"pdf-content"
    assert result["mime_type"] == "application/pdf"
    assert destination.name.startswith(result["sha256"][:12])


def test_import_is_idempotent_for_same_content(tmp_path: Path) -> None:
    service = SourceImportService()
    encoded = base64.b64encode(b"same-source").decode()

    first = service.import_base64(tmp_path, "source.pdf", encoded)
    second = service.import_base64(tmp_path, "source.pdf", encoded)

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["path"] == first["path"]


@pytest.mark.parametrize(
    ("filename", "payload", "error"),
    [
        ("../escape.pdf", b"x", "invalid_filename"),
        ("source.pdf", b"", "empty_source"),
        ("source.pdf", None, "invalid_base64"),
    ],
)
def test_import_rejects_unsafe_or_invalid_input(
    tmp_path: Path, filename: str, payload: bytes | None, error: str
) -> None:
    encoded = "not-base64" if payload is None else base64.b64encode(payload).decode()
    with pytest.raises(ImportError, match=error):
        SourceImportService().import_base64(tmp_path, filename, encoded)
