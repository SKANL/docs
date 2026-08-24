# src/docs/cli/commands/section_app.py
"""Section drafting/review commands: build-section, pack-context,
review-section, review-document.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.cli._shared import _ctx, emit_result
from docs.domain.normative import resolve_normative_settings

section_app = typer.Typer()


@section_app.command("build-section")
def build_section(ctx: typer.Context, section_id: str = typer.Argument(...)) -> None:
    """Genera el scaffold de una sección a partir de su contrato en el template.

    Escribe el encabezado gestionado por el arnés y un cuerpo de
    marcador. El cuerpo en prosa es la ranura cognitiva: se redacta a
    mano después."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.pipeline.build_section(resolved.doc_id, resolved.template, section_id, resolved.config))


@section_app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
    """Arma el paquete de contexto que el agente lee antes de redactar.

    Acepta un `<id>` de sección, `all` (todas más el paquete de
    documento) o `document` (solo el paquete transversal)."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)

    def pack_one(sid: str) -> Path:
        return deps.context_pack.pack_context(resolved.doc_id, resolved.template, sid, resolved.config, normative=normative)

    def pack_document() -> Path:
        return deps.context_pack.pack_context_document(
            resolved.doc_id, resolved.template, resolved.config,
            manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )

    if section_id == "all":
        for section in resolved.template.sections:
            print(pack_one(section.id))
        print(pack_document())
    elif section_id == "document":
        print(pack_document())
    else:
        print(pack_one(section_id))


@section_app.command("review-section")
def review_section(
    ctx: typer.Context,
    section: str = typer.Argument(...),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Revisa una sección contra su contrato y devuelve los hallazgos.

    Con `--json` emite la lista estructurada de hallazgos para iterar
    hasta verde (ver `docs guide`, §4). `--strict` aplica la política
    estricta del template. Sale con código 1 si hay hallazgos bloqueantes."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    result = deps.review.review_section(resolved.doc_id, resolved.template, section, strict=strict, normative=normative)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@section_app.command("review-document")
def review_document(
    ctx: typer.Context,
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Revisa el documento completo: coherencia entre secciones, APA y trazabilidad.

    Complementa a `review-section`, que solo mira una sección aislada.
    Sale con código 1 si hay hallazgos bloqueantes."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)
    result = deps.review.review_document(
        resolved.doc_id, resolved.template, strict=strict,
        manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)
