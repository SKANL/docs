# src/docs/cli/commands/asset_app.py
"""`asset` command group: attach .docx assets (cover, annexes) to a document.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="asset"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import typer

from docs.cli._shared import _ctx

asset_app = typer.Typer(help="Adjunta archivos .docx al documento (portada, anexos).")


@asset_app.command("add")
def asset_add(ctx: typer.Context, path: str = typer.Argument(...), name: str = typer.Option("", "--name")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    target = deps.assets.add_asset(resolved.doc_id, path, name=name)
    print(target)
    print(f"Asset `{target.stem}` agregado. Úsalo en la estructura con cover_from_asset o embed_docx.")


@asset_app.command("list")
def asset_list(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    names = deps.assets.list_assets(resolved.doc_id)
    if not names:
        print("No hay assets. Agrega uno con `asset add <ruta.docx>`.")
        return
    for name in names:
        print(f"- {name}")


@asset_app.command("rm")
def asset_rm(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.assets.remove_asset(resolved.doc_id, name)
    print(f"Asset `{name}` eliminado.")
