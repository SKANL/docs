import base64
import io
import zipfile
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
    ("filename", "payload", "expected"),
    [
        ("renamed.bin", b"%PDF-1.7\n", "application/pdf"),
        ("renamed.bin", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("renamed.bin", b"\xff\xd8\xff\xe0", "image/jpeg"),
    ],
)
def test_import_records_detected_mime_from_content(
    tmp_path: Path, filename: str, payload: bytes, expected: str
) -> None:
    result = SourceImportService().import_base64(
        tmp_path, filename, base64.b64encode(payload).decode()
    )
    assert result["mime_type"] == expected


def test_import_detects_ooxml_document_from_zip_manifest(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    result = SourceImportService().import_base64(
        tmp_path, "renamed.bin", base64.b64encode(stream.getvalue()).decode()
    )
    assert result["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
