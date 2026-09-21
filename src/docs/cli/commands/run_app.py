"""Inspection and control of durable API/worker runs."""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
import typer

from docs.cli._shared import _ctx
from docs.application.workspaces import WorkspaceRegistry
from docs.domain.contracts import Run
from docs.infrastructure.persistence.x20 import SqliteJobQueue, SqliteRunStore

run_app = typer.Typer(add_completion=False, help="Inspect and control durable runs.")


def _stores(ctx: typer.Context):
    deps, _ = _ctx(ctx)
    root = deps.workspace.documents_dir.parent.resolve()
    registry_path = root / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(
        registry_path if registry_path.is_file() else os.environ.get("DOCS_WORKSPACE_REGISTRY") or (Path.home() / ".docs" / "workspaces.json")
    )
    active = registry.active()
    if active is not None:
        root = Path(str(active["root"])).resolve()
    state = root / ".docs" / "x20.sqlite3"
    return SqliteRunStore(state), SqliteJobQueue(state)


@run_app.command("list")
def list_runs(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """List durable runs stored by the local API."""
    store, _ = _stores(ctx)
    items = [item.to_dict() for item in store.list()]
    typer.echo(json.dumps(items, ensure_ascii=False, sort_keys=True) if json_output else "\n".join(f"{x['id']}\t{x['status']}" for x in items))


@run_app.command("show")
def show_run(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show one durable run and its payload."""
    store, _ = _stores(ctx)
    item = store.get(run_id)
    if item is None:
        raise typer.BadParameter(f"Run not found: {run_id}")
    typer.echo(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) if json_output else json.dumps(item.to_dict(), ensure_ascii=False, indent=2))


@run_app.command("cancel")
def cancel_run(ctx: typer.Context, run_id: str) -> None:
    """Request cooperative cancellation of a queued run."""
    store, queue = _stores(ctx)
    item = store.get(run_id)
    if item is None:
        raise typer.BadParameter(f"Run not found: {run_id}")
    if item.status in {"succeeded", "completed", "failed", "expired", "cancelled"}:
        raise typer.BadParameter(f"Run is already terminal: {item.status}")
    cancel = getattr(queue, "cancel", None)
    if callable(cancel):
        cancel(run_id)
    store.put(Run(item.id, "cancelled", item.payload, item.created_at))
    typer.echo(json.dumps({"id": run_id, "status": "cancelled"}, sort_keys=True))


@run_app.command("retry")
def retry_run(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Queue a new attempt for a failed, cancelled, or expired run."""
    store, queue = _stores(ctx)
    original = store.get(run_id)
    if original is None:
        raise typer.BadParameter(f"Run not found: {run_id}")
    if original.status not in {"failed", "cancelled", "expired"}:
        raise typer.BadParameter("Only failed, cancelled, or expired runs can be retried")
    payload = dict(original.payload)
    retry_id = str(uuid4())
    payload.update({"run_id": retry_id, "retry_of": run_id, "attempt": int(payload.get("attempt", 1)) + 1})
    retried = Run(retry_id, payload=payload, created_at=datetime.now(UTC).isoformat())
    store.put(retried)
    queue.enqueue(retry_id, payload)
    result = retried.to_dict()
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True) if json_output else retry_id)


@run_app.command("watch")
def watch_run(
    ctx: typer.Context,
    run_id: str,
    json_output: bool = typer.Option(False, "--json"),
    interval: float = typer.Option(1.0, "--interval", min=0.1),
) -> None:
    """Follow a durable run until it reaches a terminal state."""
    store, _ = _stores(ctx)
    while True:
        item = store.get(run_id)
        if item is None:
            raise typer.BadParameter(f"Run not found: {run_id}")
        payload = item.to_dict()
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_output else f"{run_id}\t{payload['status']}")
        if payload["status"] in {"succeeded", "completed", "failed", "cancelled", "expired"}:
            return
        time.sleep(interval)
