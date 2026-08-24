# src/docs/cli/commands/context_app.py
"""`context` command group: elicit and manage the document's atomic context.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted with
`name="context"` on the root app (unchanged group name/prefix).
"""
from __future__ import annotations

import json

import typer

from docs.cli._shared import _ctx

context_app = typer.Typer(help="Elicita y gestiona el contexto atómico del documento.")


@context_app.command("status")
def context_status(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Muestra qué temas de contexto están completos y cuáles tienen campos faltantes."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    statuses = deps.context.status(resolved.doc_id, resolved.template)
    if as_json:
        print(json.dumps(
            [{"id": s.id, "title": s.title, "complete": not s.missing, "missing": s.missing} for s in statuses],
            ensure_ascii=False, indent=2,
        ))
        return
    if not statuses:
        print("La plantilla no define context_schema.")
        return
    lines = ["# Estado del contexto", ""]
    for s in statuses:
        marker = "OK" if not s.missing else "FALTA"
        missing = f" — faltan: {', '.join(s.missing)}" if s.missing else ""
        lines.append(f"- {marker} `{s.id}` ({s.title}){missing}")
    print("\n".join(lines))
    raise typer.Exit(code=0 if all(not s.missing for s in statuses) else 1)


@context_app.command("elicit")
def context_elicit(
    ctx: typer.Context,
    topic: str = typer.Option("", "--topic"),
    requests: bool = typer.Option(False, "--requests", help="(compat) el cuestionario es el único modo disponible."),
) -> None:
    """Escribe el cuestionario `_requests.md` con los campos de contexto que faltan.

    No es interactivo: genera el archivo para que se responda y luego se
    cargue con `context ingest`."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = deps.context.write_requests_file(resolved.doc_id, resolved.template, only_topic=topic)
    print(path)
    print("Rellena el cuestionario y corre `context ingest`.")


@context_app.command("ingest")
def context_ingest(ctx: typer.Context) -> None:
    """Lee las respuestas de `_requests.md` y las guarda como temas de contexto."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    written = deps.context.ingest(resolved.doc_id, resolved.template)
    print(f"Temas ingeridos: {', '.join(written) or 'ninguno'}.")


@context_app.command("show")
def context_show(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    """Imprime el contenido guardado de un tema de contexto."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.show(resolved.doc_id, topic))


@context_app.command("set")
def context_set(
    ctx: typer.Context,
    topic: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Clave del campo (ignorada en temas de prosa)."),
    value: str = typer.Argument(...),
) -> None:
    """Fija el valor de un campo de un tema de contexto.

    Ver la convención de claves `<topic> <field> <value>` en `docs guide`, §2."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.set(resolved.doc_id, resolved.template, topic, value, field=field))


@context_app.command("rm")
def context_rm(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    """Elimina un tema de contexto del documento activo."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.context.remove(resolved.doc_id, resolved.template, topic)
    print(f"Tema `{topic}` eliminado.")
