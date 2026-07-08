# tests/unit/infrastructure/test_filesystem_ingest_artifact_writer.py
"""`FilesystemIngestArtifactWriter` (design.md Decision 9): the atomic,
deterministic JSON writer every ingest-produced artifact shares."""
from __future__ import annotations

import json
from pathlib import Path

from docs.infrastructure.ingest.filesystem_ingest_artifact_writer import (
    FilesystemIngestArtifactWriter,
)


def test_write_json_creates_file_with_sorted_keys_and_no_timestamp(tmp_path: Path):
    path = tmp_path / "report.json"
    writer = FilesystemIngestArtifactWriter()

    writer.write_json(path, {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}})

    raw = path.read_text(encoding="utf-8")
    assert raw.index('"a"') < raw.index('"b"')
    assert raw.index('"y"') < raw.index('"z"')
    assert "generated_at" not in raw


def test_write_json_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "report.json"
    writer = FilesystemIngestArtifactWriter()

    writer.write_json(path, {"schema": 1})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema": 1}


def test_write_json_overwrites_existing_file_atomically(tmp_path: Path):
    path = tmp_path / "report.json"
    path.write_text('{"stale": true}', encoding="utf-8")
    writer = FilesystemIngestArtifactWriter()

    writer.write_json(path, {"fresh": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"fresh": True}


def test_write_json_leaves_no_temp_file_behind_on_success(tmp_path: Path):
    path = tmp_path / "report.json"
    writer = FilesystemIngestArtifactWriter()

    writer.write_json(path, {"schema": 1})

    leftovers = [p for p in tmp_path.iterdir() if p.name != "report.json"]
    assert leftovers == []


def test_write_json_cleans_up_temp_file_when_serialization_fails(tmp_path: Path):
    path = tmp_path / "report.json"
    writer = FilesystemIngestArtifactWriter()

    class _Unserializable:
        pass

    try:
        writer.write_json(path, {"bad": _Unserializable()})
    except TypeError:
        pass

    assert not path.exists()
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], "no orphaned .ingest-artifact-tmp-* file should survive a failed write"
