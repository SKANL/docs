# src/docs/cli/commands/template_app.py
"""`template` command group: list/show document templates.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="template"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json
from importlib.resources import files

import typer

from docs.cli._shared import _ctx, emit_result
from docs.domain.review import ReviewResult
from docs.domain.template_skeleton import build_template_skeleton
from docs.domain.template_validation import validate_template

template_app = typer.Typer(help="Gestiona los tipos de documento (plantillas).")

_BUILTIN_PACKAGE = "docs.templates.builtin"


def _list_builtin_names() -> list[str]:
    """Built-in template ids shippable as package data (design.md item C).
    `importlib.resources.files` — never a hardcoded filesystem path — so this
    resolves from an installed wheel with no repo checkout."""
    return sorted(
        entry.name.removesuffix(".json")
        for entry in files(_BUILTIN_PACKAGE).iterdir()
        if entry.name.endswith(".json")
    )


def _read_builtin(name: str) -> str:
    return files(_BUILTIN_PACKAGE).joinpath(f"{name}.json").read_text(encoding="utf-8")


@template_app.command("list")
def template_list(
    ctx: typer.Context,
    available: bool = typer.Option(False, "--available", help="Lista las plantillas integradas (package data), no las de templates_dir."),
) -> None:
    """Lista las plantillas del workspace, o las integradas con `--available`."""
    if available:
        for name in _list_builtin_names():
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
    if name not in _list_builtin_names():
        print(f"No existe la plantilla integrada `{name}`. Usa `template list --available`.")
        raise typer.Exit(code=1)
    deps, _ = _ctx(ctx)
    path = deps.workspace.templates_dir / f"{name}.json"
    if path.exists() and not force:
        print(f"Ya existe `{path}`. Usa --force para sobrescribir.")
        raise typer.Exit(code=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_read_builtin(name), encoding="utf-8")
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
