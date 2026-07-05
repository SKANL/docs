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
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.pipeline.build_section(resolved.doc_id, resolved.template, section_id, resolved.config))


@section_app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
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
