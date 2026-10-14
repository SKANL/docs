# src/docs/cli/commands/doc_crud_app.py
"""`doc` command group: CRUD for documents (isolated workspaces).

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="doc"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import typer

from docs.application.document_summary import build_document_summary
from docs.application.templates import builtin_names, read_builtin
from docs.application.workspace_config import WORKSPACE_CONFIG_FILENAME
from docs.cli._shared import _ctx, emit_result
from docs.composition import open_workspace_registry
from docs.domain.identity import pretty_json
from docs.domain.normative import resolve_normative_settings
from docs.domain.workspace_config import resolve_workspace_roots
from docs.domain.workspace_format import (
    validate_workspace_layout,
    validate_workspace_marker,
    write_workspace_marker,
)

doc_crud_app = typer.Typer(help="CRUD de documentos (workspaces aislados).")


def _activate_initialized_workspace() -> None:
    """Make ``doc init`` immediately usable by the durable run commands.

    The file-based config is enough for the document commands, but the
    asynchronous pipeline also needs a selected registry entry for its SQLite
    state and local worker.  Registering the current directory here keeps a
    freshly initialized workspace consistent across both command families.
    """
    registry = open_workspace_registry(Path.cwd() / ".docs" / "workspaces.json")
    item = registry.ensure("Local workspace", Path.cwd())
    registry.select(item["id"])


@doc_crud_app.command("init")
def doc_init(
    ctx: typer.Context,
    documents_dir: str = typer.Option("", "--documents-dir", help="Ruta de documents_dir a registrar (por defecto, la resuelta actualmente vía config/env)."),
    templates_dir: str = typer.Option("", "--templates-dir", help="Ruta de templates_dir a registrar (por defecto, la resuelta actualmente vía config/env)."),
    force: bool = typer.Option(False, "--force", help="Sobrescribe docs.config.json aunque difiera del existente."),
) -> None:
    """Bootstrapea un workspace: crea documents_dir/templates_dir, escribe
    docs.config.json con las rutas resueltas y siembra las plantillas
    integradas si templates_dir está vacío (spec: workspace-config `doc init`
    Bootstrap Command; design.md item A, reutiliza `template use` de C)."""
    del ctx
    # `doc init` bootstraps the current directory; it must not inherit a
    # previously selected workspace from the global registry. Otherwise a
    # fresh workspace silently writes its config pointing at another project.
    default_documents, default_templates = resolve_workspace_roots(
        None, os.environ, (Path("documents"), Path("templates"))
    )
    resolved_documents = documents_dir or str(default_documents)
    resolved_templates = templates_dir or str(default_templates)
    new_config = {"documents_dir": resolved_documents, "templates_dir": resolved_templates}

    root = Path.cwd().resolve()
    documents_path = Path(resolved_documents).expanduser().resolve()
    templates_path = Path(resolved_templates).expanduser().resolve()
    validate_workspace_layout(root, documents_path, templates_path)

    config_path = Path.cwd() / WORKSPACE_CONFIG_FILENAME
    if config_path.exists() and not force:
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if existing == new_config:
            validate_workspace_marker(root)
            _activate_initialized_workspace()
            print(f"El workspace ya está inicializado ({config_path}).")
            return
        print(f"Ya existe `{config_path}` con otra configuración. Usa --force para sobrescribir.")
        raise typer.Exit(code=1)

    marker_path = root / "workspace.json"
    if marker_path.exists() or (documents_path / "registry.json").exists():
        validate_workspace_marker(root)
    else:
        write_workspace_marker(root)

    config_path.write_text(
        pretty_json(new_config), encoding="utf-8"
    )

    documents_path.mkdir(parents=True, exist_ok=True)
    templates_path.mkdir(parents=True, exist_ok=True)

    if not any(templates_path.glob("*.json")):
        for name in builtin_names():
            (templates_path / f"{name}.json").write_text(read_builtin(name), encoding="utf-8")

    _activate_initialized_workspace()

    print(f"Workspace inicializado: {config_path}")
    print(f"documents_dir={documents_path}, templates_dir={templates_path}")


@doc_crud_app.command("new")
def doc_new(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), template: str = typer.Option("", "--template"), title: str = typer.Option("", "--title")) -> None:
    """Crea un documento nuevo con su workspace aislado.

    Sin `--template` usa la primera plantilla disponible; `--title` fija
    el título (por defecto, el id)."""
    deps, _ = _ctx(ctx)
    template_name = template or (deps.document_repository.list_templates()[:1] or [""])[0]
    if not template_name:
        raise RuntimeError("No hay plantillas disponibles. Crea una en templates/.")
    deps.documents.create(doc_id, template_name, title=title)
    path = deps.workspace.doc_root(doc_id) / "document.json"
    print(path)
    print(f"Documento `{doc_id}` creado desde `{template_name}` y marcado como activo.")
    print("Siguiente paso: `context status` y `context elicit` para llenar el contexto.")


@doc_crud_app.command("list")
def doc_list(ctx: typer.Context) -> None:
    """Lista los documentos registrados en el workspace."""
    deps, _ = _ctx(ctx)
    summaries = deps.documents.list()
    if not summaries:
        print("No hay documentos. Crea uno con `doc new <id>`.")
        return
    active = deps.documents.current()
    for item in summaries:
        marker = "*" if item.id == active else " "
        print(f"{marker} {item.id}  [{item.template}]  {item.title}")


@doc_crud_app.command("current")
def doc_current(ctx: typer.Context) -> None:
    """Imprime el id del documento activo."""
    deps, _ = _ctx(ctx)
    print(deps.documents.current() or "(ninguno)")


@doc_crud_app.command("show")
def doc_show(ctx: typer.Context, doc_id: str = typer.Argument("", metavar="id")) -> None:
    """Imprime el `document.json` de un documento (por defecto, el activo)."""
    deps, _ = _ctx(ctx)
    target = doc_id or deps.documents.current()
    if not target:
        raise RuntimeError("No hay documento activo.")
    document = deps.document_repository.read_document(target)
    print(json.dumps(document.model_dump(), ensure_ascii=False, indent=2))


@doc_crud_app.command("use")
def doc_use(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id")) -> None:
    """Marca un documento como activo para los comandos siguientes."""
    deps, _ = _ctx(ctx)
    deps.documents.use(doc_id)
    print(f"Documento activo: {doc_id}")


@doc_crud_app.command("rename")
def doc_rename(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), new_id: str = typer.Argument(...)) -> None:
    """Cambia el id de un documento y actualiza el registro."""
    deps, _ = _ctx(ctx)
    deps.documents.rename(doc_id, new_id)
    print(f"Renombrado: {doc_id} → {new_id}")


@doc_crud_app.command("delete")
def doc_delete(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), yes: bool = typer.Option(False, "--yes")) -> None:
    """Elimina un documento y su workspace. Pide confirmación salvo que se pase `--yes`."""
    deps, _ = _ctx(ctx)
    if not yes:
        raise RuntimeError(f"Confirma el borrado de `{doc_id}` con --yes.")
    deps.documents.delete(doc_id)
    print(f"Documento `{doc_id}` eliminado.")


@doc_crud_app.command("status")
def doc_status(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Resumen retomable del documento activo (design.md item I): contexto
    lleno/faltante, secciones redactadas/scaffold/con hallazgos, ingesta,
    figuras y salida -- para que un agente pueda retomar sin re-derivar el
    estado a mano."""
    deps, doc = _ctx(ctx)
    result, payload = build_document_summary(deps, doc)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=None, sort_keys=True))
    else:
        emit_result(result, False)


@doc_crud_app.command("revise")
def doc_revise(
    ctx: typer.Context,
    target: str = typer.Argument(..., metavar="id", help="Id de sección o de tema de contexto a revisar."),
    request: str = typer.Argument(..., help="Descripción breve de la solicitud de cambio (queda en la bitácora)."),
    body_file: str = typer.Argument(
        ..., metavar="archivo",
        help="Ruta a un .md con el cuerpo/valor de reemplazo ya editado por el agente (fuera de banda).",
    ),
    field: str = typer.Option("", "--field", help="Clave de campo (solo temas de contexto no-prosa)."),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Bucle de edición semántica (design.md item B, spec: document-revise):
    el agente ya escribió el reemplazo en `body_file`; el harness calcula el
    diff, re-valida solo lo afectado (sección/tema + review-document) y
    registra la procedencia en `sections/_revisions/revision-log.json`. No
    admite cambios estructurales (agregar/quitar secciones): usa `context
    set`/ingesta para eso."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = deps.rules_manifest_state(resolved.config)
    new_content = Path(body_file).read_text(encoding="utf-8")
    now = datetime.now().isoformat(timespec="seconds")

    kind = deps.revision.resolve_target(resolved.template, target)
    if kind == "section":
        result = deps.revision.revise(
            resolved.doc_id, resolved.template, resolved.config, target, new_content, request,
            strict=strict, manifest_exists=manifest_exists, manifest_size=manifest_size,
            normative=normative, now=now,
        )
    else:
        result = deps.revision.revise_topic(
            resolved.doc_id, resolved.template, resolved.config, target, new_content, request,
            field=field, strict=strict, manifest_exists=manifest_exists, manifest_size=manifest_size,
            normative=normative, now=now,
        )
    emit_result(result, as_json)
