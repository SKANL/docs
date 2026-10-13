"""Non-pipeline top-level CLI commands."""
from __future__ import annotations

from datetime import datetime
from importlib.resources import files
from pathlib import Path

import typer

from docs.application.document_tools import run_diagnostics
from docs.cli._shared import _ctx, emit_result
from docs.domain.issue_codes import ISSUE_CODES, explain_code
from docs.domain.review import ReviewDimension, ReviewResult

core_app = typer.Typer()
_AGENTS_MD_PACKAGE = "docs.data"
_AGENTS_MD_NAME = "AGENTS.md"


def _filter_review_dimensions(result: ReviewResult, dimensions: list[ReviewDimension] | None) -> ReviewResult:
    if not dimensions:
        return result
    return result.filter_dimensions(set(dimensions))


def _read_agents_guide() -> str:
    resource = files(_AGENTS_MD_PACKAGE).joinpath(_AGENTS_MD_NAME)
    if resource.is_file():
        return resource.read_text(encoding="utf-8")
    return (Path(__file__).resolve().parents[4] / _AGENTS_MD_NAME).read_text(encoding="utf-8")


@core_app.command()
def guide() -> None:
    """Print the canonical agent contract."""
    print(_read_agents_guide())


@core_app.command()
def explain(code: str = typer.Argument("", help="Finding code; empty lists the catalog.")) -> None:
    """Explain a review finding code."""
    print(explain_code(code or None))
    if code and code not in ISSUE_CODES:
        raise typer.Exit(code=2)


@core_app.command()
def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Check workspace readiness and native v2 capabilities."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = run_diagnostics(deps, resolved, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 2)


@core_app.command()
def stamp() -> None:
    """Print a local ISO-8601 timestamp for authored section stamps."""
    print(datetime.now().isoformat(timespec="seconds"))
