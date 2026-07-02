# src/docs/cli/main.py
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer

from docs.cli._shared import Deps, ResolvedContext, emit_result

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False, help="Arnés multi-documento para Word.")


@app.callback()
def _root(ctx: typer.Context, doc: str = typer.Option("", "--doc", help="ID del documento (por defecto, el activo).")) -> None:
    # One Deps per invocation; commands read ctx.obj.
    ctx.obj = {"deps": Deps(), "doc": doc}


def _ctx(ctx: typer.Context) -> tuple[Deps, str]:
    return ctx.obj["deps"], ctx.obj["doc"]


@app.command()
def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.doctor.run_doctor(resolved.doc_id, resolved.config, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 2)


@app.command()
def pipeline(
    ctx: typer.Context,
    stage_set: str = typer.Argument(..., help="prep | assemble | all"),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
    repo_root: Path = typer.Option(Path.cwd, "--repo-root"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    summary = deps.pipeline.run_pipeline(
        resolved.doc_id, resolved.template, resolved.config, stage_set, repo_root=repo_root, strict=strict
    )
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        lines = [f"# Pipeline `{summary['stage_set']}` (strict={summary['strict']})", ""]
        for stage in summary["stages"]:
            marker = "OK" if stage["ok"] else "FAIL"
            head = stage["detail"].splitlines()[0] if stage["detail"] else ""
            lines.append(f"- {marker} `{stage['stage']}` ({stage['duration_s']}s): {head}")
        lines.extend(["", "PASÓ" if summary["passed"] else "FALLÓ"])
        print("\n".join(lines))
    raise typer.Exit(code=0 if summary["passed"] else 1)


@app.command()
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


@app.command()
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


@app.command()
def stamp() -> None:
    print(datetime.now().isoformat(timespec="seconds"))


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, standalone_mode=False)
    except typer.Exit as exc:
        return exc.exit_code
    except Exception as exc:  # legacy main() parity (3945-3947)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
