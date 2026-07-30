# src/docs/cli/commands/core_app.py
"""Core pipeline commands: doctor, pipeline, verify, history, stamp.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from pathlib import Path

import typer

from docs.cli._shared import _ctx, emit_result, resolve_renderer

core_app = typer.Typer()

_AGENTS_MD_PACKAGE = "docs.data"
_AGENTS_MD_NAME = "AGENTS.md"


def _read_agents_guide() -> str:
    """Single-source contract content (design.md item B, ADR-B): the
    canonical file is the repo-root AGENTS.md, force-included into the
    wheel at `docs/data/AGENTS.md` so an installed package can read it with
    no repo checkout. `pyproject.toml` force-include only copies the file at
    BUILD time, so a source checkout (dev/test, `pythonpath = ["src"]`) has
    no packaged copy on disk yet -- fall back to the same file at the repo
    root in that case. Never two authored copies, only two read paths."""
    resource = files(_AGENTS_MD_PACKAGE).joinpath(_AGENTS_MD_NAME)
    if resource.is_file():
        return resource.read_text(encoding="utf-8")
    # src/docs/cli/commands/core_app.py -> parents[4] is the repo root.
    repo_root_guide = Path(__file__).resolve().parents[4] / _AGENTS_MD_NAME
    return repo_root_guide.read_text(encoding="utf-8")


@core_app.command()
def guide() -> None:
    """Imprime el contrato del agente (AGENTS.md) — flujo de trabajo
    completo, convenciones y el límite cognitivo entre el arnés y el
    agente (spec: agent-contract `docs guide` CLI Command)."""
    print(_read_agents_guide())


@core_app.command()
def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.doctor.run_doctor(resolved.doc_id, resolved.config, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 2)


@core_app.command()
def pipeline(
    ctx: typer.Context,
    stage_set: str = typer.Argument(..., help="prep | ingest | assemble | all"),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
    repo_root: Path = typer.Option(Path.cwd, "--repo-root"),
    formats: list[str] = typer.Option(
        None,
        "--format",
        help="Formato(s) de salida a construir (repetible, ej. --format html --format docx). "
        "Sin esta opción usa output.format de la config (docx por defecto).",
    ),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    # No --format: preserve today's config-driven resolution exactly (a
    # single renderer from `output.format`, default "docx") so an explicit
    # `output.format` in a template's config is never silently overridden by
    # a hardcoded CLI default. --format (repeatable): build exactly the
    # requested formats via the same registry-resolution function.
    if formats:
        renderers = [resolve_renderer(deps.renderers, fmt) for fmt in formats]
    else:
        renderers = [deps.resolve_renderer(resolved.config)]

    summaries = [
        deps.pipeline.run_pipeline(
            resolved.doc_id, resolved.template, resolved.config, stage_set,
            repo_root=repo_root, strict=strict, renderer=renderer,
        )
        for renderer in renderers
    ]
    passed = all(summary["passed"] for summary in summaries)

    if as_json:
        # Backward compatible: a single (default, unflagged) format still
        # prints one JSON object, not a one-item list.
        payload = summaries[0] if len(summaries) == 1 else summaries
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for summary in summaries:
            lines = [f"# Pipeline `{summary['stage_set']}` (strict={summary['strict']})", ""]
            for stage in summary["stages"]:
                marker = "OK" if stage["ok"] else "FAIL"
                head = stage["detail"].splitlines()[0] if stage["detail"] else ""
                lines.append(f"- {marker} `{stage['stage']}` ({stage['duration_s']}s): {head}")
            lines.extend(["", "PASÓ" if summary["passed"] else "FALLÓ"])
            print("\n".join(lines))
    raise typer.Exit(code=0 if passed else 1)


@core_app.command()
def verify(
    ctx: typer.Context,
    docx: str = typer.Argument("", help="DOCX opcional; por defecto el draft."),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
    repo_root: Path = typer.Option(Path.cwd, "--repo-root"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    docx_path = Path(docx) if docx else None
    result = deps.pipeline.verify_all(resolved.doc_id, resolved.template, resolved.config, docx_path=docx_path, strict=strict)
    deps.pipeline.log_run(
        resolved.doc_id, resolved.config, repo_root, "verify",
        {"strict": strict, "passed": result.passed, "issues": [i.to_dict() for i in result.issues]},
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@core_app.command()
def history(ctx: typer.Context, limit: int = typer.Option(20, "--limit"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    records = deps.pipeline.list_runs(resolved.doc_id, resolved.config, limit=limit)
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return
    if not records:
        print("Sin corridas registradas en runs/.")
        return
    lines = ["# Historial de corridas", ""]
    for record in records:
        status = record.get("passed")
        marker = "OK" if status else ("FAIL" if status is False else "·")
        lines.append(f"- {record.get('timestamp', '')} {marker} `{record.get('command', '')}` @ {record.get('git_commit', '')}")
    print("\n".join(lines))


@core_app.command()
def stamp() -> None:
    print(datetime.now().isoformat(timespec="seconds"))
