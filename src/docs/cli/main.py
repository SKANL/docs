# src/docs/cli/main.py
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer

from docs.cli._shared import Deps, ResolvedContext, emit_result
from docs.domain.normative import resolve_normative_settings
from docs.domain.rules import review_rules as domain_review_rules

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


@app.command("collect-sources")
def collect_sources(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_sources(resolved.config))


@app.command("build-rules")
def build_rules(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.evidence.build_rules(resolved.config))


@app.command("review-rules")
def review_rules(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
    result = domain_review_rules(resolved.template, manifest_exists, manifest_size, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("collect-issues")
def collect_issues(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_issues(resolved.config, repo_root))


@app.command("collect-code-evidence")
def collect_code_evidence(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_code_evidence(resolved.config, repo_root))


@app.command("build-ledger")
def build_ledger(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = Path(resolved.config["paths"]["fact_ledger"])
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _context_confirmed_lines(deps, resolved.doc_id, resolved.template)
    path.write_text(deps.evidence.render_fact_ledger(resolved.config, lines), encoding="utf-8")
    print(path)


def _rules_manifest_state(deps: Deps, config: dict) -> tuple[bool, int]:
    rules_path = Path(config["paths"]["rules_manifest"])
    exists = rules_path.exists()
    return exists, (rules_path.stat().st_size if exists else 0)


def _context_confirmed_lines(deps: Deps, doc_id: str, template) -> list[str]:
    # Mirrors PipelineService._context_confirmed_lines (Slice 14 JC4): sensitive
    # topic fields are skipped, not mis-classified.
    lines: list[str] = []
    for topic in template.context_schema.topics:
        values = deps.context_repository.read_topic(doc_id, topic)
        if isinstance(values, dict):
            for field in topic.fields:
                value = values.get(field.key, "")
                if not value or field.sensitive:
                    continue
                lines.append(f"{field.label}: {value}")
        elif isinstance(values, str) and values.strip():
            lines.append(f"{topic.title or topic.id}: {values.strip()[:160]}")
    return lines


_BUILD_SECTION_UNAVAILABLE = (
    "build-section requiere un renderer de borradores y source_hash/prompt_hash "
    "aún no modelados en esta migración (ver Slice 6 y Slice 8, Design Decision 4)."
)


@app.command("build-section")
def build_section(ctx: typer.Context, section_id: str = typer.Argument(...)) -> None:
    # Judgment call 3: surface the unmodeled gap cleanly, do not fake hashes.
    print(f"ERROR: {_BUILD_SECTION_UNAVAILABLE}", file=sys.stderr)
    raise typer.Exit(code=1)


@app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)

    def pack_one(sid: str) -> Path:
        return deps.context_pack.pack_context(resolved.doc_id, resolved.template, sid, resolved.config, **normative)

    def pack_document() -> Path:
        return deps.context_pack.pack_context_document(
            resolved.doc_id, resolved.template, resolved.config,
            manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
        )

    if section_id == "all":
        for section in resolved.template.sections:
            print(pack_one(section.id))
        print(pack_document())
    elif section_id == "document":
        print(pack_document())
    else:
        print(pack_one(section_id))


@app.command("review-section")
def review_section(
    ctx: typer.Context,
    section: str = typer.Argument(...),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    result = deps.review.review_section(resolved.doc_id, resolved.template, section, strict=strict, **normative)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("review-document")
def review_document(
    ctx: typer.Context,
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
    result = deps.review.review_document(
        resolved.doc_id, resolved.template, strict=strict,
        manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("build-docx")
def build_docx(ctx: typer.Context, output: str = typer.Option("", "--output")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.docx.build(resolved.doc_id, resolved.config, Path(output) if output else None))


@app.command("qa-docx")
def qa_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.qa.qa_docx(resolved.config, Path(docx), strict=strict))


@app.command("format-audit-docx")
def format_audit_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.format_audit.audit_format(Path(docx), resolved.config, strict=strict)
    print(result.to_markdown())
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("apply-corrections")
def apply_corrections(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    count = deps.corrections.apply_corrections(resolved.doc_id, resolved.config)
    print(f"Correcciones aplicadas: {count}")


@app.command("stamp-section")
def stamp_section(ctx: typer.Context, section_id: str = typer.Argument(...), by: str = typer.Option(..., "--by"), model: str = typer.Option("", "--model")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    now = datetime.now().isoformat(timespec="seconds")
    print(deps.review.stamp_section(resolved.doc_id, resolved.template, section_id, authored_by=by, model=model, now=now))


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
