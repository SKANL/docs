from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from docs.application.workspace_migration import (
    CANONICAL_FORMAT,
    CURRENT_UNVERSIONED_FORMAT,
    UNKNOWN_FORMAT,
    WorkspaceMigrationInspector,
)

CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)


def _snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_current_unversioned_fixture_is_the_only_supported_legacy_shape() -> None:
    report = WorkspaceMigrationInspector().inspect(CURRENT_UNVERSIONED)

    assert report.detected_format == CURRENT_UNVERSIONED_FORMAT
    assert report.ready
    assert report.errors == ()
    assert report.omitted == ()
    assert report.excluded == ()
    assert report.unknown == ()
    assert len(report.preserved) == len(_snapshot(CURRENT_UNVERSIONED))
    assert report.record("documents/sanitized-report/sections/004-opaque-source.md").sha256 == (
        hashlib.sha256(
            (CURRENT_UNVERSIONED / "documents/sanitized-report/sections/004-opaque-source.md").read_bytes()
        ).hexdigest()
    )


def test_canonical_copy_is_recognized_idempotently(tmp_path: Path) -> None:
    source = tmp_path / "canonical"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    (source / "workspace.json").write_text('{"schema":"docs.workspace/v1"}\n', encoding="utf-8")

    report = WorkspaceMigrationInspector().inspect(source)

    assert report.detected_format == CANONICAL_FORMAT
    assert report.ready
    assert report.transformations == ()
    assert report.record("workspace.json").disposition == "preserved"


def test_inspection_creates_no_source_destination_or_parent_records(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"
    before_source = _snapshot(source)
    before_parent = set(tmp_path.iterdir())

    report = WorkspaceMigrationInspector().inspect(source, destination=destination)

    assert report.detected_format == CURRENT_UNVERSIONED_FORMAT
    assert report.destination == destination.resolve()
    assert _snapshot(source) == before_source
    assert set(tmp_path.iterdir()) == before_parent
    assert not destination.exists()


def test_unversioned_lookalike_without_evidenced_registry_shape_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "documents").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "documents" / "registry.json").write_text(
        '{"schema":2,"active":null,"documents":[]}', encoding="utf-8"
    )

    report = WorkspaceMigrationInspector().inspect(tmp_path)

    assert report.detected_format == UNKNOWN_FORMAT
    assert report.errors[0].code == "document_registry_unsupported"
    assert not report.ready
