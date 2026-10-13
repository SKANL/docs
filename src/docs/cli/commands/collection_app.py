# src/docs/cli/commands/collection_app.py
"""Source/evidence collection commands: collect-sources, build-rules,
review-rules, collect-issues, collect-code-evidence, build-ledger.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.application.document_tools import check_rules, write_fact_ledger
from docs.cli._shared import _ctx, emit_result

collection_app = typer.Typer()


@collection_app.command("collect-sources")
def collect_sources(ctx: typer.Context) -> None:
    """Inventaria las fuentes declaradas del documento y escribe el manifiesto de fuentes."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_sources(resolved.config))


@collection_app.command("build-rules")
def build_rules(ctx: typer.Context) -> None:
    """Construye el manifiesto de reglas normativas a partir de la configuración vigente."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.evidence.build_rules(resolved.config))


@collection_app.command("review-rules")
def review_rules(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Verifica que el manifiesto de reglas exista y sea consistente con el template.

    Sale con código 1 si falta o no cumple. `--strict` endurece el criterio."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = check_rules(deps, resolved, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@collection_app.command("collect-issues")
def collect_issues(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    """Recolecta issues de GitHub del repositorio indicado como evidencia trazable.

    Requiere `gh` en PATH. `--repo-root` indica el repo a consultar (por
    defecto, el directorio actual)."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_issues(resolved.config, repo_root))


@collection_app.command("collect-code-evidence")
def collect_code_evidence(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    """Recolecta evidencia de código (historial git de los archivos declarados) para el ledger."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_code_evidence(resolved.config, repo_root))


@collection_app.command("build-ledger")
def build_ledger(ctx: typer.Context) -> None:
    """Escribe el ledger de hechos: contexto confirmado más la evidencia ya recolectada."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(write_fact_ledger(deps, resolved))
