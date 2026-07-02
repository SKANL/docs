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
    lines = deps.pipeline.context_confirmed_lines(resolved.doc_id, resolved.template)
    path.write_text(deps.evidence.render_fact_ledger(resolved.config, lines), encoding="utf-8")
    print(path)


def _rules_manifest_state(deps: Deps, config: dict) -> tuple[bool, int]:
    rules_path = Path(config["paths"]["rules_manifest"])
    exists = rules_path.exists()
    return exists, (rules_path.stat().st_size if exists else 0)


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


template_app = typer.Typer(help="Gestiona los tipos de documento (plantillas).")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    names = deps.document_repository.list_templates()
    if not names:
        print("No hay plantillas en templates/.")
        return
    for name in names:
        template = deps.document_repository.load_template(name)
        print(f"- {name}: {template.title}")


@template_app.command("show")
def template_show(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    template = deps.document_repository.load_template(name)
    print(json.dumps(template.model_dump(), ensure_ascii=False, indent=2))


doc_app = typer.Typer(help="CRUD de documentos (workspaces aislados).")
app.add_typer(doc_app, name="doc")


@doc_app.command("new")
def doc_new(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), template: str = typer.Option("", "--template"), title: str = typer.Option("", "--title")) -> None:
    deps, _ = _ctx(ctx)
    template_name = template or (deps.document_repository.list_templates()[:1] or [""])[0]
    if not template_name:
        raise RuntimeError("No hay plantillas disponibles. Crea una en templates/.")
    deps.documents.create(doc_id, template_name, title=title)
    path = deps.workspace.doc_root(doc_id) / "document.json"
    print(path)
    print(f"Documento `{doc_id}` creado desde `{template_name}` y marcado como activo.")
    print("Siguiente paso: `context status` y `context elicit` para llenar el contexto.")


@doc_app.command("list")
def doc_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    summaries = deps.documents.list()
    if not summaries:
        print("No hay documentos. Crea uno con `doc new <id>`.")
        return
    active = deps.documents.current()
    for item in summaries:
        marker = "*" if item.id == active else " "
        print(f"{marker} {item.id}  [{item.template}]  {item.title}")


@doc_app.command("current")
def doc_current(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    print(deps.documents.current() or "(ninguno)")


@doc_app.command("show")
def doc_show(ctx: typer.Context, doc_id: str = typer.Argument("", metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    target = doc_id or deps.documents.current()
    if not target:
        raise RuntimeError("No hay documento activo.")
    document = deps.document_repository.read_document(target)
    print(json.dumps(document.model_dump(), ensure_ascii=False, indent=2))


@doc_app.command("use")
def doc_use(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.use(doc_id)
    print(f"Documento activo: {doc_id}")


@doc_app.command("rename")
def doc_rename(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), new_id: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.rename(doc_id, new_id)
    print(f"Renombrado: {doc_id} → {new_id}")


@doc_app.command("delete")
def doc_delete(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), yes: bool = typer.Option(False, "--yes")) -> None:
    deps, _ = _ctx(ctx)
    if not yes:
        raise RuntimeError(f"Confirma el borrado de `{doc_id}` con --yes.")
    deps.documents.delete(doc_id)
    print(f"Documento `{doc_id}` eliminado.")


asset_app = typer.Typer(help="Adjunta archivos .docx al documento (portada, anexos).")
app.add_typer(asset_app, name="asset")


@asset_app.command("add")
def asset_add(ctx: typer.Context, path: str = typer.Argument(...), name: str = typer.Option("", "--name")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    target = deps.assets.add_asset(resolved.doc_id, path, name=name)
    print(target)
    print(f"Asset `{target.stem}` agregado. Úsalo en la estructura con cover_from_asset o embed_docx.")


@asset_app.command("list")
def asset_list(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    names = deps.assets.list_assets(resolved.doc_id)
    if not names:
        print("No hay assets. Agrega uno con `asset add <ruta.docx>`.")
        return
    for name in names:
        print(f"- {name}")


@asset_app.command("rm")
def asset_rm(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.assets.remove_asset(resolved.doc_id, name)
    print(f"Asset `{name}` eliminado.")


context_app = typer.Typer(help="Elicita y gestiona el contexto atómico del documento.")
app.add_typer(context_app, name="context")


@context_app.command("status")
def context_status(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    statuses = deps.context.status(resolved.doc_id, resolved.template)
    if as_json:
        print(json.dumps(
            [{"id": s.id, "title": s.title, "complete": not s.missing, "missing": s.missing} for s in statuses],
            ensure_ascii=False, indent=2,
        ))
        return
    if not statuses:
        print("La plantilla no define context_schema.")
        return
    lines = ["# Estado del contexto", ""]
    for s in statuses:
        marker = "OK" if not s.missing else "FALTA"
        missing = f" — faltan: {', '.join(s.missing)}" if s.missing else ""
        lines.append(f"- {marker} `{s.id}` ({s.title}){missing}")
    print("\n".join(lines))
    raise typer.Exit(code=0 if all(not s.missing for s in statuses) else 1)


@context_app.command("elicit")
def context_elicit(
    ctx: typer.Context,
    topic: str = typer.Option("", "--topic"),
    requests: bool = typer.Option(False, "--requests", help="(compat) el cuestionario es el único modo disponible."),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = deps.context.write_requests_file(resolved.doc_id, resolved.template, only_topic=topic)
    print(path)
    print("Rellena el cuestionario y corre `context ingest`.")


@context_app.command("ingest")
def context_ingest(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    written = deps.context.ingest(resolved.doc_id, resolved.template)
    print(f"Temas ingeridos: {', '.join(written) or 'ninguno'}.")


@context_app.command("show")
def context_show(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.show(resolved.doc_id, topic))


@context_app.command("set")
def context_set(
    ctx: typer.Context,
    topic: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Clave del campo (ignorada en temas de prosa)."),
    value: str = typer.Argument(...),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.set(resolved.doc_id, resolved.template, topic, value, field=field))


@context_app.command("rm")
def context_rm(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.context.remove(resolved.doc_id, resolved.template, topic)
    print(f"Tema `{topic}` eliminado.")


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
