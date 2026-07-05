# tests/unit/domain/test_ingest_naming.py
from pathlib import Path

from docs.domain.ingest_naming import ingested_output_path, sha256_hex


def test_sha256_hex_matches_hashlib_reference():
    import hashlib

    data = b"some source bytes"
    assert sha256_hex(data) == hashlib.sha256(data).hexdigest()


def test_ingested_output_path_builds_stem_kind_sha8_name():
    result = ingested_output_path(Path("/out"), "readme", "docx", "abcd1234")
    assert result == Path("/out/readme-docx-abcd1234.md")
