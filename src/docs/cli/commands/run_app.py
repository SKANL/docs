"""Inspection and control of durable API/worker runs."""
from __future__ import annotations

import json
import time
from pathlib import Path
import typer

from docs.cli._shared import _ctx
from docs.application.workspaces import WorkspaceRegistry
from docs.infrastructure.persistence.x20 import SqliteJobQueue, SqliteRunStore

run_app = typer.Typer(add_completion=False, help="Inspect and control durable runs.")


def _stores(ctx: typer.Context):
    deps, _ = _ctx(ctx)
    root = deps.workspace.documents_dir.parent.resolve()
    registry = WorkspaceRegistry(root / ".docs" / "workspaces.json")
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
    cancel = getattr(queue, "cancel", None)
    if callable(cancel):
        cancel(run_id)
    typer.echo(json.dumps({"id": run_id, "status": "cancelled"}, sort_keys=True))


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
