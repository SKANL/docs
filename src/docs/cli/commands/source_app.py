"""Public source pipeline command namespace."""
from __future__ import annotations

import json
from typing import Any

import typer

from docs.application.source_pipeline import SourcePipeline
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter

source_app = typer.Typer(help="Source ingestion and normalization commands.")


def create_source_pipeline(deps: Any) -> SourcePipeline | None:
    """Build the source use case from the shared application composition."""
    ingest = getattr(deps, "ingest", None)
    if ingest is None:
        return None
    normalizer = getattr(deps, "markdown_normalizer", None) or MdNormalizeAdapter()
    file_writer = getattr(deps, "atomic_file_writer", None) or AtomicFileAdapter()
    return SourcePipeline(ingest, normalizer, file_writer)


def run_source_command(ctx: typer.Context, command: str, json_output: bool) -> None:
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    root = deps.workspace.doc_root(resolved.doc_id)
    service = create_source_pipeline(deps)
    if service is None:
        raise typer.BadParameter("source ingest dependencies are unavailable")
    report = (
        service.ingest(resolved.doc_id, root, resolved.config)
        if command == "ingest"
        else service.prepare(resolved.doc_id, root, resolved.config)
    )
    if command == "prepare" and report.get("succeeded"):
        template = getattr(resolved, "template", None)
        report["scaffolds"] = (
            [
                str(deps.section.build_section(resolved.doc_id, template, section.id, resolved.config))
                for section in template.sections
            ]
            if template is not None
            else []
        )
    output = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    typer.echo(output if json_output else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["succeeded"]:
        raise typer.Exit(code=1)


@source_app.command("ingest")
def source_ingest(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ingest source material through the native v2 source stage."""
    run_source_command(ctx, "ingest", json_output)
