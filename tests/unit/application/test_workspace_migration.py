from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from docs.application.workspace_migration import (
    CANONICAL_FORMAT,
    CURRENT_UNVERSIONED_FORMAT,
    UNKNOWN_FORMAT,
    WorkspaceMigrationError,
    WorkspaceMigrationInspector,
    WorkspaceMigrationPublisher,
)
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository


def _write_current_workspace(root: Path) -> None:
    (root / "documents" / "report").mkdir(parents=True)
    (root / "templates").mkdir()
    (root / "documents" / "registry.json").write_text(
        json.dumps(
            {
                "active": "report",
                "documents": [
                    {
                        "created_at": "2026-09-26T00:00:00Z",
                        "id": "report",
                        "template": "generic",
                        "title": "Report",
                    }
                ],
                "schema": 1,
            }
        ),
        encoding="utf-8",
    )
    (root / "documents" / "report" / "document.json").write_text(
        '{"id":"report","template":"generic"}', encoding="utf-8"
    )
    (root / "templates" / "generic.json").write_text('{"type":"generic"}', encoding="utf-8")


def test_inspector_hashes_raw_registry_before_direct_parsing(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    registry = tmp_path / "documents" / "registry.json"
    raw = registry.read_bytes()

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == CURRENT_UNVERSIONED_FORMAT
    record = report.record("documents/registry.json")
    assert record.size == len(raw)
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert record.disposition == "preserved"


def test_inspector_never_uses_document_repository_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_current_workspace(tmp_path)

    def forbidden_fallback(*args: object, **kwargs: object) -> object:
        raise AssertionError("JsonDocumentRepository fallback was used")

    monkeypatch.setattr(JsonDocumentRepository, "load_registry", forbidden_fallback)

    assert WorkspaceMigrationInspector().inspect(tmp_path).detected_format == CURRENT_UNVERSIONED_FORMAT


def test_canonical_marker_is_the_only_version_discriminator(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    (tmp_path / "workspace.json").write_text('{"schema":"docs.workspace/v1"}\n', encoding="utf-8")

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == CANONICAL_FORMAT
    assert report.ready
    assert report.transformations == ()


def test_malformed_marker_never_falls_back_to_unversioned(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    (tmp_path / "workspace.json").write_text('{"schema":"docs.workspace/v2"}', encoding="utf-8")

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == UNKNOWN_FORMAT
    assert [error.code for error in report.errors] == ["workspace_schema_unsupported"]
    assert not report.ready


def test_malformed_registry_reports_original_path_and_hash(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    registry = tmp_path / "documents" / "registry.json"
    raw = b'{"schema":1,"documents":['
    registry.write_bytes(raw)

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == UNKNOWN_FORMAT
    assert report.errors[0].code == "document_registry_malformed"
    assert report.errors[0].path == "documents/registry.json"
    assert report.errors[0].sha256 == hashlib.sha256(raw).hexdigest()


def test_registry_path_traversal_is_rejected_from_raw_registry(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    registry = tmp_path / "documents" / "registry.json"
    value = json.loads(registry.read_text(encoding="utf-8"))
    value["documents"][0]["id"] = "../escape"
    registry.write_text(json.dumps(value), encoding="utf-8")

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == UNKNOWN_FORMAT
    assert report.errors[0].code == "document_registry_unsafe_path"


def test_paths_are_classified_without_silently_copying_unknown_records(tmp_path: Path) -> None:
    _write_current_workspace(tmp_path)
    doc = tmp_path / "documents" / "report"
    (doc / "sections").mkdir()
    (doc / "sections" / "001-overview.md").write_text("# OVERVIEW\n", encoding="utf-8")
    (doc / "output" / "qa" / "previews").mkdir(parents=True)
    (doc / "output" / "qa" / "previews" / "page-1.png").write_bytes(b"preview")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "queue.json").write_text("{}", encoding="utf-8")
    (tmp_path / "docs.config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "mystery.bin").write_bytes(b"unknown")

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.record("documents/report/sections/001-overview.md").disposition == "preserved"
    assert report.record("documents/report/output/qa/previews/page-1.png").disposition == "omitted"
    assert report.record("runs/queue.json").disposition == "excluded"
    assert report.record("docs.config.json").disposition == "excluded"
    assert report.record("mystery.bin").disposition == "unknown"
    assert [error.code for error in report.errors] == ["unknown_workspace_record"]
    assert not report.ready


def test_publisher_requires_an_absent_separate_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    _write_current_workspace(source)
    destination.mkdir()

    with pytest.raises(WorkspaceMigrationError, match="destination_must_be_absent"):
        WorkspaceMigrationPublisher().publish(source, destination)

    with pytest.raises(WorkspaceMigrationError, match="destination_must_be_separate"):
        WorkspaceMigrationPublisher().publish(source, source)
