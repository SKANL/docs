# tests/unit/infrastructure/test_json_evidence_repository.py
import hashlib
import json
from pathlib import Path

import pytest

from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def repo() -> JsonEvidenceRepository:
    return JsonEvidenceRepository()


def test_hash_file_matches_raw_sha256_of_bytes(tmp_path: Path, repo):
    path = tmp_path / "a.md"
    path.write_bytes(b"hello world")
    assert repo.hash_file(path) == hashlib.sha256(b"hello world").hexdigest()


def test_hash_json_matches_sorted_ensure_ascii_false_dump(repo):
    value = {"b": 1, "a": "café"}
    expected = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert repo.hash_json(value) == expected


def test_list_manual_files_sorted_md_glob(tmp_path: Path, repo):
    (tmp_path / "01-b.md").write_text("b")
    (tmp_path / "00-a.md").write_text("a")
    (tmp_path / "ignore.txt").write_text("x")
    files = repo.list_manual_files(tmp_path)
    assert [f.name for f in files] == ["00-a.md", "01-b.md"]


def test_read_text_replaces_invalid_bytes(tmp_path: Path, repo):
    path = tmp_path / "bad.md"
    path.write_bytes(b"valid \xff\xfe invalid")
    text = repo.read_text(path)
    assert "valid" in text and "invalid" in text


def test_file_exists_and_file_size(tmp_path: Path, repo):
    path = tmp_path / "f.md"
    path.write_bytes(b"12345")
    assert repo.file_exists(path) is True
    assert repo.file_size(path) == 5
    assert repo.file_exists(tmp_path / "missing.md") is False


def test_list_traceability_files_filters_by_suffix_and_files_only(tmp_path: Path, repo):
    (tmp_path / "note.md").write_text("a")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "image.png").write_text("x")
    (tmp_path / "sub").mkdir()
    files = repo.list_traceability_files(tmp_path)
    assert sorted(f.name for f in files) == ["data.json", "note.md"]


def test_list_traceability_files_suffix_case_insensitive(tmp_path: Path, repo):
    (tmp_path / "NOTE.MD").write_text("a")
    files = repo.list_traceability_files(tmp_path)
    assert [f.name for f in files] == ["NOTE.MD"]


def test_read_manifest_returns_none_when_missing(tmp_path: Path, repo):
    assert repo.read_manifest(tmp_path / "missing.json") is None


def test_read_manifest_returns_none_when_invalid_json(tmp_path: Path, repo):
    path = tmp_path / "bad.json"
    path.write_text("not json")
    assert repo.read_manifest(path) is None


def test_read_manifest_returns_parsed_dict(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1}))
    assert repo.read_manifest(path) == {"schema": 1}


def test_write_manifest_creates_file_with_generated_at_and_sorted_keys(tmp_path: Path, repo):
    path = tmp_path / "sub" / "manifest.json"
    repo.write_manifest(path, {"schema": 1, "b": 2, "a": 1})
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["schema"] == 1
    assert "generated_at" in payload
    assert text.index('"a"') < text.index('"b"')  # sort_keys=True


def test_write_manifest_skips_write_when_content_unchanged_ignoring_generated_at(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    repo.write_manifest(path, {"schema": 1})
    first_text = path.read_text(encoding="utf-8")
    repo.write_manifest(path, {"schema": 1})
    second_text = path.read_text(encoding="utf-8")
    assert first_text == second_text  # generated_at unchanged: no rewrite happened


def test_write_manifest_rewrites_with_new_generated_at_when_content_changes(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    repo.write_manifest(path, {"schema": 1, "manual_files": []})
    first_generated_at = json.loads(path.read_text(encoding="utf-8"))["generated_at"]
    repo.write_manifest(path, {"schema": 1, "manual_files": [{"name": "x.md"}]})
    second = json.loads(path.read_text(encoding="utf-8"))
    assert second["manual_files"] == [{"name": "x.md"}]
    assert "generated_at" in second


def test_write_manifest_treats_corrupt_existing_file_as_absent(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    path.write_text("not json")
    repo.write_manifest(path, {"schema": 1})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert "generated_at" in payload
