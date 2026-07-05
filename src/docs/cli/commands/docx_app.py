# src/docs/cli/commands/docx_app.py
"""DOCX build/QA commands: build-docx, qa-docx, format-audit-docx,
apply-corrections, stamp-section.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from docs.cli._shared import _ctx

docx_app = typer.Typer()


@docx_app.command("build-docx")
def build_docx(ctx: typer.Context, output: str = typer.Option("", "--output")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.docx.build(resolved.doc_id, resolved.config, Path(output) if output else None))


@docx_app.command("qa-docx")
def qa_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.qa.qa_docx(resolved.config, Path(docx), strict=strict))


@docx_app.command("format-audit-docx")
def format_audit_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.format_audit.audit_format(Path(docx), resolved.config, strict=strict)
    print(result.to_markdown())
    raise typer.Exit(code=0 if result.passed else 1)


@docx_app.command("apply-corrections")
def apply_corrections(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    count = deps.corrections.apply_corrections(resolved.doc_id, resolved.config)
    print(f"Correcciones aplicadas: {count}")


@docx_app.command("stamp-section")
def stamp_section(ctx: typer.Context, section_id: str = typer.Argument(...), by: str = typer.Option(..., "--by"), model: str = typer.Option("", "--model")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    now = datetime.now().isoformat(timespec="seconds")
    print(deps.review.stamp_section(resolved.doc_id, resolved.template, section_id, authored_by=by, model=model, now=now))
