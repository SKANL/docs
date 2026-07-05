# src/docs/cli/commands/collection_app.py
"""Source/evidence collection commands: collect-sources, build-rules,
review-rules, collect-issues, collect-code-evidence, build-ledger.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.cli._shared import _ctx, emit_result
from docs.domain.rules import review_rules as domain_review_rules

collection_app = typer.Typer()


@collection_app.command("collect-sources")
def collect_sources(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_sources(resolved.config))


@collection_app.command("build-rules")
def build_rules(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.evidence.build_rules(resolved.config))


@collection_app.command("review-rules")
def review_rules(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)
    result = domain_review_rules(resolved.template, manifest_exists, manifest_size, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@collection_app.command("collect-issues")
def collect_issues(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_issues(resolved.config, repo_root))


@collection_app.command("collect-code-evidence")
def collect_code_evidence(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_code_evidence(resolved.config, repo_root))


@collection_app.command("build-ledger")
def build_ledger(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = Path(resolved.config["paths"]["fact_ledger"])
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = deps.pipeline.context_confirmed_lines(resolved.doc_id, resolved.template)
    path.write_text(deps.evidence.render_fact_ledger(resolved.config, lines), encoding="utf-8")
    print(path)
