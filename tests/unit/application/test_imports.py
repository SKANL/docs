import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from docs.application.imports import ImportError, SourceImportService

CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)


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


def test_import_normalizes_underscores_to_workspace_safe_document_id(tmp_path: Path) -> None:
    result = SourceImportService().import_base64(
        tmp_path,
        "source.pdf",
        base64.b64encode(b"source").decode(),
        document_id="Compilado_Anexo22_2025 (1)",
    )
    assert result["document_id"] == "compilado-anexo22-2025-1"


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


def test_current_unversioned_fixture_preserves_source_path_bytes_hash_and_identity(
    tmp_path: Path,
) -> None:
    inbox = CURRENT_UNVERSIONED / "documents" / "sanitized-report" / "inbox"
    source = inbox / "da544f726ca4-source.bin"
    payload = source.read_bytes()
    expected_hash = "da544f726ca44fe8403759872375b74ffd25c300eaa9345193d67fb665b775f2"

    assert payload == b"\x00Sanitized source bytes.\r\nSecond line.\r\n"
    assert hashlib.sha256(payload).hexdigest() == expected_hash
    source_manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    manifest_entry = source_manifest["sources"][0]
    assert manifest_entry["relative_path"] == source.name
    assert manifest_entry["sha256"] == expected_hash

    imported = SourceImportService().import_bytes(
        tmp_path,
        "source.bin",
        payload,
        document_id="sanitized-report",
    )
    imported_path = Path(imported["path"])
    assert imported["id"] == f"import-{expected_hash[:16]}"
    assert imported["sha256"] == expected_hash
    assert imported_path.name == source.name
    assert imported_path.read_bytes() == payload
