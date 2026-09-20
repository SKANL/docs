"""Inspection and control of durable API/worker runs."""
from __future__ import annotations

import json
import typer

from docs.cli._shared import _ctx
from docs.infrastructure.persistence.x20 import SqliteJobQueue, SqliteRunStore

run_app = typer.Typer(add_completion=False, help="Inspect and control durable runs.")


def _stores(ctx: typer.Context):
    deps, _ = _ctx(ctx)
    state = deps.workspace.documents_dir.parent / ".docs" / "x20.sqlite3"
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
