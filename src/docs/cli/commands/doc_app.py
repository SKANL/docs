# src/docs/cli/commands/doc_app.py
"""`doc` command group: CRUD for documents (isolated workspaces).

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="doc"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json

import typer

from docs.cli._shared import _ctx

doc_app = typer.Typer(help="CRUD de documentos (workspaces aislados).")


@doc_app.command("new")
def doc_new(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), template: str = typer.Option("", "--template"), title: str = typer.Option("", "--title")) -> None:
    deps, _ = _ctx(ctx)
    template_name = template or (deps.document_repository.list_templates()[:1] or [""])[0]
    if not template_name:
        raise RuntimeError("No hay plantillas disponibles. Crea una en templates/.")
    deps.documents.create(doc_id, template_name, title=title)
    path = deps.workspace.doc_root(doc_id) / "document.json"
    print(path)
    print(f"Documento `{doc_id}` creado desde `{template_name}` y marcado como activo.")
    print("Siguiente paso: `context status` y `context elicit` para llenar el contexto.")


@doc_app.command("list")
def doc_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    summaries = deps.documents.list()
    if not summaries:
        print("No hay documentos. Crea uno con `doc new <id>`.")
        return
    active = deps.documents.current()
    for item in summaries:
        marker = "*" if item.id == active else " "
        print(f"{marker} {item.id}  [{item.template}]  {item.title}")


@doc_app.command("current")
def doc_current(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    print(deps.documents.current() or "(ninguno)")


@doc_app.command("show")
def doc_show(ctx: typer.Context, doc_id: str = typer.Argument("", metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    target = doc_id or deps.documents.current()
    if not target:
        raise RuntimeError("No hay documento activo.")
    document = deps.document_repository.read_document(target)
    print(json.dumps(document.model_dump(), ensure_ascii=False, indent=2))


@doc_app.command("use")
def doc_use(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.use(doc_id)
    print(f"Documento activo: {doc_id}")


@doc_app.command("rename")
def doc_rename(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), new_id: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.rename(doc_id, new_id)
    print(f"Renombrado: {doc_id} → {new_id}")


@doc_app.command("delete")
def doc_delete(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), yes: bool = typer.Option(False, "--yes")) -> None:
    deps, _ = _ctx(ctx)
    if not yes:
        raise RuntimeError(f"Confirma el borrado de `{doc_id}` con --yes.")
    deps.documents.delete(doc_id)
    print(f"Documento `{doc_id}` eliminado.")
