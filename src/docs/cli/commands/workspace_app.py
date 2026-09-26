from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from docs.application.workspace_migration import (
    MigrationInspectionError,
    MigrationRecord,
    WorkspaceMigrationInspection,
    WorkspaceMigrationInspector,
)
from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError

workspace_app = typer.Typer(help="Manage persistent Doc Harness workspaces.")


def _registry() -> WorkspaceRegistry:
    return WorkspaceRegistry()


def _migration_record_payload(record: MigrationRecord) -> dict[str, Any]:
    return {
        "disposition": record.disposition,
        "path": record.path,
        "sha256": record.sha256,
        "size": record.size,
    }


def _migration_error_payload(error: MigrationInspectionError) -> dict[str, Any]:
    return {"code": error.code, "path": error.path, "sha256": error.sha256}


def _migration_payload(report: WorkspaceMigrationInspection) -> dict[str, Any]:
    return {
        "destination": str(report.destination) if report.destination is not None else None,
        "detected_format": report.detected_format,
        "errors": [_migration_error_payload(error) for error in report.errors],
        "excluded": [_migration_record_payload(record) for record in report.excluded],
        "mode": "dry-run",
        "omitted": [_migration_record_payload(record) for record in report.omitted],
        "preserved": [_migration_record_payload(record) for record in report.preserved],
        "publication_policy": report.publication_policy,
        "ready": report.ready,
        "recovery_guidance": report.recovery_guidance,
        "scratch_policy": "not-created-in-dry-run",
        "selected_roots": [str(report.source_root)],
        "source_root": str(report.source_root),
        "transformations": list(report.transformations),
        "unknown": [_migration_record_payload(record) for record in report.unknown],
    }


def _print_migration_records(label: str, records: list[dict[str, Any]]) -> None:
    print(f"{label} ({len(records)}):")
    if not records:
        print("  - none")
        return
    for record in records:
        print(f"  - {record['path']} ({record['size']} bytes, sha256={record['sha256']})")


def _print_migration_report(payload: dict[str, Any]) -> None:
    print(f"Mode: {payload['mode']}")
    print(f"Source: {payload['source_root']}")
    print(f"Destination: {payload['destination']}")
    print(f"Detected format: {payload['detected_format']}")
    print(f"Ready: {'yes' if payload['ready'] else 'no'}")
    _print_migration_records("Preserved", payload["preserved"])
    _print_migration_records("Omitted", payload["omitted"])
    _print_migration_records("Excluded", payload["excluded"])
    _print_migration_records("Unknown", payload["unknown"])
    print("Transformations:")
    for transformation in payload["transformations"] or ["none"]:
        print(f"  - {transformation}")
    print("Errors:")
    if not payload["errors"]:
        print("  - none")
    else:
        for error in payload["errors"]:
            digest = f", sha256={error['sha256']}" if error["sha256"] is not None else ""
            print(f"  - {error['code']}: {error['path']}{digest}")
    print(f"Publication policy: {payload['publication_policy']}")
    print(f"Scratch policy: {payload['scratch_policy']}")
    print(f"Recovery guidance: {payload['recovery_guidance']}")


@workspace_app.command("migrate")
def migrate_workspace(
    source: Path = typer.Option(..., "--source", help="Rooted workspace to inspect."),
    destination: Path = typer.Option(
        ..., "--destination", help="Separate destination that must not exist."
    ),
    dry_run: bool = typer.Option(True, "--dry-run", help="Inspect only; never writes files."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Report a rooted workspace migration plan without changing any state."""
    if not dry_run:
        raise typer.BadParameter("only_dry_run_is_supported")
    resolved_destination = destination.expanduser().resolve()
    if resolved_destination.exists():
        raise typer.BadParameter("destination_must_be_absent", param_hint="--destination")

    report = WorkspaceMigrationInspector().inspect(source, destination=resolved_destination)
    payload = _migration_payload(report)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_migration_report(payload)
    if not report.ready:
        raise typer.Exit(code=2)


@workspace_app.command("list")
def list_workspaces(as_json: bool = typer.Option(False, "--json")) -> None:
    """List registered workspaces and mark the active one."""
    payload = {"items": _registry().list(), "active": _registry().active()}
    if as_json:
        import json
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for item in payload["items"]:
            marker = "*" if payload["active"] and payload["active"]["id"] == item["id"] else " "
            print(f"{marker} {item['id']}  {item['name']}  {item['root']}")


@workspace_app.command("create")
def create_workspace(name: str, root: Path, as_json: bool = typer.Option(False, "--json")) -> None:
    """Create a workspace rooted at ROOT."""
    try:
        item = _registry().create(name, root)
    except WorkspaceRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if as_json:
        import json
        print(json.dumps(item, ensure_ascii=False, sort_keys=True))
    else:
        print(item["id"])


@workspace_app.command("use")
def use_workspace(workspace_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Select a registered workspace by id."""
    try:
        item = _registry().select(workspace_id)
        if as_json:
            import json
            print(json.dumps(item, ensure_ascii=False, sort_keys=True))
        else:
            print(item["root"])
    except WorkspaceRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc


@workspace_app.command("rename")
def rename_workspace(workspace_id: str, name: str) -> None:
    """Rename a registered workspace without moving its files."""
    try:
        print(_registry().rename(workspace_id, name)["name"])
    except WorkspaceRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc


@workspace_app.command("delete")
def delete_workspace(workspace_id: str) -> None:
    """Remove a workspace from the registry without deleting its files."""
    try:
        _registry().delete(workspace_id)
    except WorkspaceRegistryError as exc:
        raise typer.BadParameter(str(exc)) from exc


@workspace_app.command("status")
def workspace_status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Show the active workspace or workspace_not_configured."""
    item = _registry().active()
    if as_json:
        import json
        print(json.dumps(item, indent=2, sort_keys=True))
    else:
        print(item["root"] if item else "workspace_not_configured")
