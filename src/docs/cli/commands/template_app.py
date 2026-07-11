# src/docs/cli/commands/template_app.py
"""`template` command group: list/show document templates.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="template"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json

import typer

from docs.cli._shared import _ctx, emit_result
from docs.domain.review import ReviewResult
from docs.domain.template_skeleton import build_template_skeleton
from docs.domain.template_validation import validate_template

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


@template_app.command("init")
def template_init(ctx: typer.Context, doc_type: str = typer.Argument(..., help="Tipo de documento (nombre de la plantilla).")) -> None:
    """Emite un esqueleto documentado con cada bloque de política reconocido
    (spec: document-template "init emits a documented skeleton")."""
    deps, _ = _ctx(ctx)
    skeleton = build_template_skeleton(doc_type)
    path = deps.workspace.templates_dir / f"{doc_type}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Plantilla `{doc_type}` creada en {path}.")
    print(f"Complete los TODO y ejecute `template validate {doc_type}` antes de usarla.")


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
    path = deps.workspace.templates_dir / f"{doc_type}.json"
    if not path.exists():
        print(f"No existe la plantilla `{doc_type}` en {path}.")
        raise typer.Exit(code=1)
    raw = json.loads(path.read_text(encoding="utf-8"))
    result = ReviewResult(validate_template(raw))
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)
