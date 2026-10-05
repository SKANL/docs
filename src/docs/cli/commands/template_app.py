# src/docs/cli/commands/template_app.py
"""`template` command group: list/show document templates.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="template"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json

import typer

from docs.application.templates import TemplateError, TemplateService, builtin_names
from docs.cli._shared import _ctx, emit_result

template_app = typer.Typer(help="Gestiona los tipos de documento (plantillas).")

@template_app.command("list")
def template_list(
    ctx: typer.Context,
    available: bool = typer.Option(False, "--available", help="Lista las plantillas integradas (package data), no las de templates_dir."),
) -> None:
    """Lista las plantillas del workspace, o las integradas con `--available`."""
    if available:
        for name in builtin_names():
            print(f"- {name}")
        return
    deps, _ = _ctx(ctx)
    names = deps.document_repository.list_templates()
    if not names:
        print("No hay plantillas en templates/.")
        return
    for name in names:
        template = deps.document_repository.load_template(name)
        print(f"- {name}: {template.title}")


@template_app.command("use")
def template_use(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Id de la plantilla integrada (ver `template list --available`)."),
    force: bool = typer.Option(False, "--force", help="Sobrescribe una plantilla existente en templates_dir."),
) -> None:
    """Copia una plantilla integrada (package data) a templates_dir (design.md
    item C: `template use`, lo que `doc init` reutiliza para sembrar un
    workspace vacío)."""
    deps, _ = _ctx(ctx)
    try:
        path = TemplateService(deps.workspace.templates_dir).use(name, force=force)
    except TemplateError as exc:
        if exc.code == "builtin_template_not_found":
            print(f"No existe la plantilla integrada `{name}`. Usa `template list --available`.")
        else:
            print(exc)
        raise typer.Exit(code=1) from exc
    print(f"Plantilla `{name}` copiada a {path}.")


@template_app.command("show")
def template_show(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    """Imprime el JSON completo de una plantilla, con los valores por defecto ya resueltos."""
    deps, _ = _ctx(ctx)
    template = deps.document_repository.load_template(name)
    print(json.dumps(template.model_dump(), ensure_ascii=False, indent=2))


@template_app.command("init")
def template_init(ctx: typer.Context, doc_type: str = typer.Argument(..., help="Tipo de documento (nombre de la plantilla).")) -> None:
    """Emite un esqueleto documentado con cada bloque de política reconocido
    (spec: document-template "init emits a documented skeleton")."""
    deps, _ = _ctx(ctx)
    try:
        path = TemplateService(deps.workspace.templates_dir).create(doc_type, overwrite=True)
    except TemplateError as exc:
        print(exc)
        raise typer.Exit(code=1) from exc
    print(f"Plantilla `{doc_type}` creada en {path}.")
    print(f"Complete los TODO y ejecute `template validate {doc_type}` antes de usarla.")


@template_app.command("create")
def template_create(
    ctx: typer.Context,
    doc_type: str = typer.Argument(..., help="Type of document (template name)."),
) -> None:
    """Create a new declarative template skeleton."""
    template_init(ctx, doc_type)


@template_app.command("validate")
def template_validate(
    ctx: typer.Context,
    doc_type: str = typer.Argument(..., help="Tipo de documento (nombre de la plantilla)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Valida estructura y completitud sin exigir un modelo estricto
    (spec: document-template "Template Structural and Completeness
    Validation")."""
    deps, _ = _ctx(ctx)
    try:
        result = TemplateService(deps.workspace.templates_dir).validate(doc_type)
    except TemplateError as exc:
        print(exc)
        raise typer.Exit(code=1) from exc
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)
