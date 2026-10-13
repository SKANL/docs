from __future__ import annotations

from pathlib import Path

import typer

from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from docs.composition import open_workspace_registry

workspace_app = typer.Typer(help="Manage persistent Doc Harness workspaces.")


def _registry() -> WorkspaceRegistry:
    """Resolve the cwd-local registry before configured/global fallbacks.

    ``doc init`` activates its workspace in ``.docs/workspaces.json`` so the
    workspace command group must consult that same registry.  When no local
    registry exists, ``WorkspaceRegistry`` retains its explicit environment
    variable and global-home fallback behavior.
    """
    local_registry = Path.cwd() / ".docs" / "workspaces.json"
    return open_workspace_registry(local_registry if local_registry.is_file() else None)


@workspace_app.command("list")
def list_workspaces(as_json: bool = typer.Option(False, "--json")) -> None:
    """List registered workspaces and mark the active one."""
    registry = _registry()
    items = registry.list()
    active = registry.active()
    payload = {"items": items, "active": active}
    if as_json:
        import json
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for item in items:
            marker = "*" if active is not None and active["id"] == item["id"] else " "
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
