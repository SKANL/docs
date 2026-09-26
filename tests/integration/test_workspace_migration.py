from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from docs.application.workspace_migration import (
    CANONICAL_FORMAT,
    CURRENT_UNVERSIONED_FORMAT,
    UNKNOWN_FORMAT,
    WorkspaceMigrationInspector,
    WorkspaceMigrationPublisher,
)
from docs.cli.main import app

CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)
runner = CliRunner()


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


def test_cli_dry_run_emits_deterministic_json_without_mutating_any_state(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"
    config = tmp_path / "docs.config.json"
    config.write_text('{"documents_dir":"elsewhere"}\n', encoding="utf-8")
    registry = tmp_path / "workspaces.json"
    registry.write_text('{"active":null,"workspaces":[]}\n', encoding="utf-8")
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(registry))
    monkeypatch.chdir(tmp_path)
    before_source = _snapshot(source)
    before_config = config.read_bytes()
    before_registry = registry.read_bytes()
    before_parent = set(tmp_path.iterdir())

    arguments = [
        "workspace",
        "migrate",
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--dry-run",
        "--json",
    ]
    first = runner.invoke(app, arguments)
    second = runner.invoke(app, arguments)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first.output == second.output
    payload = json.loads(first.output)
    assert payload == {
        "destination": str(destination.resolve()),
        "detected_format": CURRENT_UNVERSIONED_FORMAT,
        "errors": [],
        "excluded": [],
        "mode": "dry-run",
        "omitted": [],
        "preserved": payload["preserved"],
        "publication_policy": "separate-absent-destination",
        "published": False,
        "ready": True,
        "recovery_guidance": "source-remains-unchanged-until-explicit-cutover",
        "scratch_policy": "not-created-in-dry-run",
        "selected_roots": [str(source.resolve())],
        "source_root": str(source.resolve()),
        "transformations": ["add-canonical-workspace-marker"],
        "unknown": [],
    }
    assert payload["preserved"]
    assert _snapshot(source) == before_source
    assert config.read_bytes() == before_config
    assert registry.read_bytes() == before_registry
    assert set(tmp_path.iterdir()) == before_parent
    assert not destination.exists()


def test_cli_human_report_matches_json_decisions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"

    result = runner.invoke(
        app,
        [
            "workspace",
            "migrate",
            "--source",
            str(source),
            "--destination",
            str(destination),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Mode: dry-run" in result.output
    assert f"Source: {source.resolve()}" in result.output
    assert f"Destination: {destination.resolve()}" in result.output
    assert f"Detected format: {CURRENT_UNVERSIONED_FORMAT}" in result.output
    assert "Ready: yes" in result.output
    assert "Transformations:\n  - add-canonical-workspace-marker" in result.output
    assert "Publication policy: separate-absent-destination" in result.output
    assert "Scratch policy: not-created-in-dry-run" in result.output
    assert "Recovery guidance: source-remains-unchanged-until-explicit-cutover" in result.output


def test_cli_requires_explicit_source_and_absent_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"
    destination.mkdir()

    missing_source = runner.invoke(
        app, ["workspace", "migrate", "--destination", str(tmp_path / "new-destination")]
    )
    missing_destination = runner.invoke(
        app, ["workspace", "migrate", "--source", str(source)]
    )
    existing_destination = runner.invoke(
        app,
        [
            "workspace",
            "migrate",
            "--source",
            str(source),
            "--destination",
            str(destination),
        ],
    )
    conflicting_modes = runner.invoke(
        app,
        [
            "workspace",
            "migrate",
            "--source",
            str(source),
            "--destination",
            str(tmp_path / "another-destination"),
            "--dry-run",
            "--apply",
        ],
    )

    assert missing_source.exit_code == 2
    assert missing_destination.exit_code == 2
    assert existing_destination.exit_code == 2
    assert "destination_must_be_absent" in existing_destination.output
    assert conflicting_modes.exit_code == 2
    assert "dry_run_and_apply_are_mutually_exclusive" in conflicting_modes.output
    assert list(destination.iterdir()) == []


def test_publication_copies_preserved_bytes_and_leaves_source_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    generated = source / "documents" / "sanitized-report" / "output" / "draft.docx"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_bytes(b"rebuildable")
    destination = tmp_path / "destination"
    before_source = _snapshot(source)
    inspection = WorkspaceMigrationInspector().inspect(source, destination=destination)

    publication = WorkspaceMigrationPublisher().publish(source, destination)

    assert publication.inspection == inspection
    assert publication.destination == destination.resolve()
    assert publication.published
    assert _snapshot(source) == before_source
    assert not (destination / generated.relative_to(source)).exists()
    assert (destination / "workspace.json").read_bytes() == b'{"schema":"docs.workspace/v1"}\n'
    for record in inspection.preserved:
        source_bytes = (source / record.path).read_bytes()
        destination_bytes = (destination / record.path).read_bytes()
        assert destination_bytes == source_bytes
        assert hashlib.sha256(destination_bytes).hexdigest() == record.sha256


def test_publication_failure_cleans_scratch_and_preserves_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"
    before_source = _snapshot(source)
    original = WorkspaceMigrationPublisher._copy_record
    calls = 0

    def fail_after_one_copy(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected-copy-failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(WorkspaceMigrationPublisher, "_copy_record", fail_after_one_copy)

    try:
        WorkspaceMigrationPublisher().publish(source, destination)
    except OSError as exc:
        assert str(exc) == "injected-copy-failure"
    else:
        raise AssertionError("expected injected publication failure")

    assert _snapshot(source) == before_source
    assert not destination.exists()
    assert not list(tmp_path.glob(".destination.migration-*"))


def test_cli_apply_is_explicit_and_publishes_without_touching_external_state(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    shutil.copytree(CURRENT_UNVERSIONED, source)
    destination = tmp_path / "destination"
    config = tmp_path / "docs.config.json"
    config.write_bytes(b'{"documents_dir":"source/documents"}\n')
    registry = tmp_path / "workspaces.json"
    registry.write_bytes(b'{"active":null,"workspaces":[]}\n')
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(registry))
    before_source = _snapshot(source)
    before_config = config.read_bytes()
    before_registry = registry.read_bytes()

    result = runner.invoke(
        app,
        [
            "workspace",
            "migrate",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--apply",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "apply"
    assert payload["published"] is True
    assert payload["scratch_policy"] == "removed-after-atomic-publication"
    assert destination.is_dir()
    assert _snapshot(source) == before_source
    assert config.read_bytes() == before_config
    assert registry.read_bytes() == before_registry
