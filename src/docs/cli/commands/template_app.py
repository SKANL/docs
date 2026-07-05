# src/docs/cli/commands/template_app.py
"""`template` command group: list/show document templates.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="template"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json

import typer

from docs.cli._shared import _ctx

template_app = typer.Typer(help="Gestiona los tipos de documento (plantillas).")


@template_app.command("list")
def template_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    names = deps.document_repository.list_templates()
    if not names:
        print("No hay plantillas en templates/.")
        return
    for name in names:
        template = deps.document_repository.load_template(name)
        print(f"- {name}: {template.title}")


@template_app.command("show")
def template_show(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    template = deps.document_repository.load_template(name)
    print(json.dumps(template.model_dump(), ensure_ascii=False, indent=2))
