# src/docs/cli/commands/core_app.py
"""Core pipeline commands: doctor, pipeline, verify, history, stamp.

Split out of cli/main.py (PR3 — CLI Composition Root Split); mounted flat
(no name prefix) on the root app so the command surface stays identical.
"""
from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import typer

from docs.application.flat_pipeline_compatibility import route_for, strict_policy_error
from docs.application.source_pipeline_v2 import SourcePipelineV2
from docs.cli._shared import _ctx, emit_result, resolve_renderer
from docs.cli.commands.v2_app import _capabilities_for
from docs.domain.issue_codes import ISSUE_CODES, explain_code
from docs.domain.review import ReviewDimension, ReviewResult
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter

core_app = typer.Typer()

_AGENTS_MD_PACKAGE = "docs.data"
_AGENTS_MD_NAME = "AGENTS.md"


def _source_pipeline_v2(deps: Any) -> SourcePipelineV2 | None:
    ingest = getattr(deps, "ingest", None)
    if ingest is None:
        return None
    return SourcePipelineV2(
        ingest,
        getattr(deps, "markdown_normalizer", None) or MdNormalizeAdapter(),
        getattr(deps, "atomic_file_writer", None) or AtomicFileAdapter(),
    )


def _v2_failure_report(
    document_id: str,
    error: str,
    code: str,
    message: str,
    expected_stages: tuple[str, ...] = ("ingest-sources",),
) -> dict[str, Any]:
    stages = [{
        "name": expected_stages[0],
        "succeeded": False,
        "result": {"error": error},
    }]
    stages.extend(
        {
            "name": stage,
            "succeeded": False,
            "skipped": True,
            "result": {
                "status": "skipped",
                "reason": "dependency_failed",
                "depends_on": expected_stages[index - 1],
            },
        }
        for index, stage in enumerate(expected_stages[1:], start=1)
    )
    return {
        "schema": "docs.sources/v2",
        "document_id": document_id,
        "succeeded": False,
        "stages": stages,
        "artifacts": [],
        "error": {"error": error},
        "errors": [{"code": code, "message": message}],
    }


def _strict_advisory_message(stage_set: str) -> str:
    """Describe strict degradation using the route the user invoked."""

    return f"--strict is advisory for the v2 {stage_set} adapter because it does not accept strict."


def _run_compatible_pipeline(
    deps: Any,
    resolved: Any,
    stage_set: str,
    strict: bool,
) -> dict[str, Any] | None:
    route = route_for(stage_set)
    if route is None:
        return None
    fallback_stage_name = route.expected_stages[0] if len(route.expected_stages) == 1 else route.stage_set
    report_label = f"v2 {stage_set}"
    report: dict[str, Any]
    supports_strict = False
    try:
        service = _source_pipeline_v2(deps)
    except Exception as exc:
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline construction failed",
            "pipeline.v2_construction_failed",
            f"The v2 source pipeline could not be constructed: {exc}",
            route.expected_stages,
        )
        service = None
    else:
        if service is None:
            report = _v2_failure_report(
                resolved.doc_id,
                "v2 source pipeline construction failed",
                "pipeline.v2_construction_failed",
                "The v2 source pipeline could not be constructed because its dependencies are incomplete.",
                route.expected_stages,
            )
        else:
            try:
                operation = getattr(service, route.operation)
            except Exception as exc:
                report = _v2_failure_report(
                    resolved.doc_id,
                    "v2 source pipeline operation lookup failed",
                    "pipeline.v2_operation_lookup_failed",
                    f"The v2 source pipeline operation could not be resolved: {exc}",
                    route.expected_stages,
                )
                operation = None
            if operation is not None:
                try:
                    document_root = deps.workspace.doc_root(resolved.doc_id)
                except Exception as exc:
                    report = _v2_failure_report(
                        resolved.doc_id,
                        "v2 source pipeline invocation failed",
                        "pipeline.v2_invocation_failed",
                        f"The v2 source pipeline invocation failed: {exc}",
                        route.expected_stages,
                    )
                    operation = None
                else:
                    args = (resolved.doc_id, document_root, resolved.config)
                if operation is not None:
                    try:
                        parameters = inspect.signature(operation).parameters.values()
                        supports_strict = any(
                            (
                                parameter.name == "strict"
                                and parameter.kind
                                in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
                            )
                            or parameter.kind is inspect.Parameter.VAR_KEYWORD
                            for parameter in parameters
                        )
                    except (TypeError, ValueError):
                        supports_strict = False
                    try:
                        report = operation(*args, strict=strict) if supports_strict else operation(*args)
                    except Exception as exc:
                        report = _v2_failure_report(
                            resolved.doc_id,
                            "v2 source pipeline invocation failed",
                            "pipeline.v2_invocation_failed",
                            f"The v2 source pipeline invocation failed: {exc}",
                            route.expected_stages,
                        )
    if not isinstance(report, Mapping):
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned malformed report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report must be a mapping.",
            route.expected_stages,
        )
    else:
        report = dict(report)
    report_document_id = report.get("document_id")
    if not isinstance(report_document_id, str) or not report_document_id.strip():
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned malformed document_id",
            "pipeline.malformed_v2_report",
            "The v2 source report must contain a non-empty document_id matching the resolved document.",
            route.expected_stages,
        )
    elif report_document_id != resolved.doc_id:
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned mismatched document_id",
            "pipeline.malformed_v2_report",
            "The v2 source report document_id must match resolved document.",
            route.expected_stages,
        )
    strict_policy = report.get("strict_policy")
    if not isinstance(strict_policy, dict):
        if strict_policy is None:
            strict_policy = {
                "requested": strict,
                "applied": False,
                "mode": "advisory",
            }
        else:
            report = _v2_failure_report(
                resolved.doc_id,
                "v2 source pipeline returned malformed strict policy",
                "pipeline.malformed_strict_policy",
                f"The {report_label} strict_policy must be a mapping.",
                route.expected_stages,
            )
            strict_policy = {
                "requested": strict,
                "applied": False,
                "mode": "advisory",
            }
    else:
        strict_policy = dict(strict_policy)
        policy_error = strict_policy_error(strict_policy, strict)
        if policy_error is not None:
            report = _v2_failure_report(
                resolved.doc_id,
                "v2 source pipeline returned malformed strict policy",
                "pipeline.malformed_strict_policy",
                f"The {report_label} strict_policy is contradictory: {policy_error}",
                route.expected_stages,
            )
            strict_policy = dict(strict_policy)
        elif strict and strict_policy.get("applied") is not True:
            strict_policy.update({
                "requested": True,
                "applied": False,
                "mode": "advisory",
            })
    report["strict_policy"] = strict_policy
    warnings = report.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    upstream_warning = strict_policy.get("warning")
    if isinstance(upstream_warning, str) and upstream_warning:
        warnings.append({
            "code": "pipeline.strict_policy",
            "message": upstream_warning,
        })
    strict_applied = strict_policy.get("applied") is True
    advisory_message = _strict_advisory_message(stage_set)
    if strict and not strict_applied and "warning" not in strict_policy:
        strict_policy["warning"] = f"v2 {stage_set} does not expose strict enforcement"
        warnings.append({
            "code": "pipeline.strict_advisory",
            "message": advisory_message,
        })
    elif strict and not strict_applied:
        warnings.append({
            "code": "pipeline.strict_advisory",
            "message": advisory_message,
        })
    if warnings:
        report["warnings"] = warnings
    required_fields = ("schema", "succeeded", "stages")
    missing_fields = [field for field in required_fields if field not in report]
    stages = report.get("stages")
    stage_shape_valid = False
    if missing_fields:
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned incomplete report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report is missing required fields: " + ", ".join(missing_fields) + ".",
            route.expected_stages,
        )
        stage = report["stages"][0]
    elif report["schema"] != "docs.sources/v2":
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned unsupported schema",
            "pipeline.malformed_v2_report",
            f"The {report_label} report schema must be exactly docs.sources/v2.",
            route.expected_stages,
        )
        stage = report["stages"][0]
    elif not isinstance(report["succeeded"], bool):
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned malformed report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report contained a malformed top-level succeeded value.",
            route.expected_stages,
        )
        stage = report["stages"][0]
    elif not isinstance(stages, list):
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned malformed report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report stages must be a list.",
            route.expected_stages,
        )
        stage = report["stages"][0]
    elif not stages:
        report["succeeded"] = False
        stage = {
            "name": fallback_stage_name,
            "succeeded": False,
            "result": {"error": "v2 source pipeline returned no stages"},
        }
        report["error"] = stage["result"]
        report["errors"] = [{
            "code": "pipeline.empty_v2_report",
            "message": f"The {report_label} report contained no stages.",
        }]
    elif len(stages) != len(route.expected_stages):
        report["succeeded"] = False
        stage = {
            "name": fallback_stage_name,
            "succeeded": False,
            "result": {"error": "v2 source pipeline returned unexpected stage records"},
        }
        report["error"] = stage["result"]
        report["errors"] = [{
            "code": "pipeline.malformed_v2_report",
            "message": (
                "The v2 source report must contain exactly "
                f"{len(route.expected_stages)} stage records for {stage_set}."
            ),
        }]
    else:
        if not all(
            isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and bool(item["name"])
            and isinstance(item.get("succeeded"), bool)
            and item.get("name") == expected_name
            for item, expected_name in zip(stages, route.expected_stages, strict=True)
        ):
            report["succeeded"] = False
            stage = {
                "name": fallback_stage_name,
                "succeeded": False,
                "result": {
                    "error": (
                        "v2 source pipeline returned malformed first stage"
                        if len(route.expected_stages) == 1
                        else "v2 source pipeline returned malformed stage records"
                    )
                },
            }
            report["error"] = stage["result"]
            report["errors"] = [{
                "code": "pipeline.malformed_v2_report",
                "message": (
                    f"The {report_label} report contained a malformed first stage."
                    if len(route.expected_stages) == 1
                    else "The v2 source report contained malformed or unexpected stage records."
                ),
            }]
        else:
            contradictory_skipped = any(
                item.get("skipped") is True and item["succeeded"] is True for item in stages
            )
            if contradictory_skipped:
                report["succeeded"] = False
                stage = {
                    "name": fallback_stage_name,
                    "succeeded": False,
                    "result": {"error": "v2 source pipeline returned contradictory skipped success values"},
                }
                report["error"] = stage["result"]
                report["errors"] = [{
                    "code": "pipeline.malformed_v2_report",
                    "message": "The v2 source report cannot mark a stage skipped and succeeded.",
                }]
            else:
                projected_succeeded = all(item["succeeded"] for item in stages)
            if not contradictory_skipped and report["succeeded"] != projected_succeeded:
                report["succeeded"] = False
                stage = {
                    "name": fallback_stage_name,
                    "succeeded": False,
                    "result": {"error": "v2 source pipeline returned contradictory success values"},
                }
                report["error"] = stage["result"]
                report["errors"] = [{
                    "code": "pipeline.malformed_v2_report",
                    "message": "The v2 source report cannot disagree with its stage success values.",
                }]
            elif not contradictory_skipped:
                stage_shape_valid = True
    if stage_shape_valid and "artifacts" not in report:
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned incomplete report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report is missing required fields: artifacts.",
            route.expected_stages,
        )
        stage = report["stages"][0]
    elif stage_shape_valid and not isinstance(report["artifacts"], list):
        report = _v2_failure_report(
            resolved.doc_id,
            "v2 source pipeline returned malformed report",
            "pipeline.malformed_v2_report",
            f"The {report_label} report artifacts must be a list.",
            route.expected_stages,
        )
        stage = report["stages"][0]
    if "strict_policy" not in report:
        strict_policy = {
            "requested": strict,
            "applied": False,
            "mode": "advisory",
        }
        report["strict_policy"] = strict_policy
        if strict:
            strict_policy["warning"] = f"v2 {stage_set} does not expose strict enforcement"
            report["warnings"] = [{
                "code": "pipeline.strict_advisory",
                "message": _strict_advisory_message(stage_set),
            }]
    detail = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return {
        "stage_set": stage_set,
        "strict": strict,
        "passed": report["succeeded"],
        "strict_policy": report["strict_policy"],
        **({"warnings": report["warnings"]} if "warnings" in report else {}),
        **({"errors": report["errors"]} if "errors" in report else {}),
        "stages": (
            [
                {
                    "stage": item["name"],
                    "ok": item["succeeded"],
                    **({"skipped": True} if item.get("skipped") is True else {}),
                    "duration_s": 0.0,
                    "detail": detail,
                }
                for item in report["stages"]
            ]
            if stage_shape_valid
            else [{
                "stage": stage["name"],
                "ok": stage["succeeded"],
                **({"skipped": True} if stage.get("skipped") is True else {}),
                "duration_s": 0.0,
                "detail": detail,
            }]
        ),
    }


def _filter_review_dimensions(
    result: ReviewResult, dimensions: list[ReviewDimension] | None
) -> ReviewResult:
    """Limit verification output to requested artifact/review dimensions."""
    if not dimensions:
        return result
    return result.filter_dimensions(set(dimensions))


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
def explain(
    code: str = typer.Argument("", help="Código de hallazgo, ej. `apa.required`. Vacío lista todo."),
) -> None:
    """Explica un código de hallazgo del ciclo de revisión: qué significa y cómo se resuelve.

    Sin argumento imprime el catálogo completo, agrupado por familia. No
    necesita workspace ni documento activo: es consultable desde cualquier
    lado. Sale con código 2 si el código no existe (y sugiere los parecidos).
    """
    print(explain_code(code or None))
    if code and code not in ISSUE_CODES:
        raise typer.Exit(code=2)


@core_app.command()
def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Verifica que el entorno y el workspace estén listos para construir.

    Revisa toolchains externos (pandoc, LibreOffice, Java, mmdc, resvg),
    rutas de configuración y assets. `--strict` convierte en error los
    chequeos que en modo normal son advertencia. Sale con código 2 si
    algún chequeo requerido falla."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.doctor.run_doctor(resolved.doc_id, resolved.config, strict=strict)
    output = resolved.config.get("output", {})
    output_format = output.get("format", "docx") if isinstance(output, dict) else "docx"
    invalid_format_diagnostic: dict[str, str | bool | None] | None = None
    try:
        renderer = deps.resolve_renderer(resolved.config)
    except (AttributeError, TypeError, ValueError):
        renderer = None
        invalid_format_diagnostic = {
            "available": False,
            "path": None,
            "required": True,
            "policy": "required",
            "kind": "format",
            "version": None,
            "diagnostic": f"Formato de salida no registrado: '{output_format}'.",
            "requirement": "a registered output renderer",
            "degradation": "diagnostics only; rendering remains unavailable",
        }
    registry = _capabilities_for(
        renderer,
        str(output_format),
        deps.workspace.doc_root(resolved.doc_id),
    )
    result.capabilities = registry.report()
    result.capability_diagnostics = registry.diagnostics()
    if invalid_format_diagnostic is not None:
        result.capabilities["output_format"] = {
            "available": False,
            "path": None,
        }
        result.capability_diagnostics["output_format"] = invalid_format_diagnostic
    result.capabilities = dict(sorted(result.capabilities.items()))
    result.capability_diagnostics = dict(sorted(result.capability_diagnostics.items()))
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 2)


@core_app.command()
def pipeline(
    ctx: typer.Context,
    stage_set: str = typer.Argument(..., help="prep | ingest | prepare | assemble | all"),
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
    """Ejecuta un conjunto de etapas de principio a fin.

    `prep` deja el documento listo para redactar (doctor, reglas,
    evidencia, secciones scaffold, gap-report, pack-context). `ingest`
    convierte lo que haya en `inbox/` y regenera los archivos de
    contexto. `prepare` ejecuta el pipeline nativo v2 de fuentes
    (ingest, normalización y estructura) sin reemplazar al `prep` legacy.
    `assemble` genera visuales y arma la salida. `all` = prep +
    review-document + assemble, y NO incluye ingest: corré `ingest` antes
    si hay fuentes nuevas. `--strict` bloquea ante huecos y hallazgos."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    compatible_summary = _run_compatible_pipeline(deps, resolved, stage_set, strict)
    if compatible_summary is not None:
        if as_json:
            print(json.dumps(compatible_summary, ensure_ascii=False, indent=2))
        else:
            stages = compatible_summary["stages"]
            if not stages:
                print(
                    "\n".join(
                        [
                            f"# Pipeline `{stage_set}` (strict={strict})",
                            "",
                            f"FAIL: {compatible_summary['errors'][0]['message']}",
                            "",
                            "FALLÓ",
                        ]
                    )
                )
                raise typer.Exit(code=1)
            lines = []
            for stage in stages:
                marker = "SKIP" if stage.get("skipped") is True else ("OK" if stage["ok"] else "FAIL")
                head = stage["detail"].splitlines()[0] if stage["detail"] else ""
                lines.append(f"- {marker} `{stage['stage']}` ({stage['duration_s']}s): {head}")
            print(
                "\n".join(
                    [
                        f"# Pipeline `{stage_set}` (strict={strict})",
                        "",
                        *lines,
                        "",
                        "PASÓ" if compatible_summary["passed"] else "FALLÓ",
                    ]
                )
            )
        raise typer.Exit(code=0 if compatible_summary["passed"] else 1)
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
        deps.legacy_pipeline.run_pipeline(
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
                marker = "SKIP" if stage.get("skipped") is True else ("OK" if stage["ok"] else "FAIL")
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
    dimensions: list[ReviewDimension] | None = typer.Option(
        None,
        "--dimension",
        help="Limita los hallazgos a una dimensión; se puede repetir.",
    ),
) -> None:
    """Revalida el documento y su .docx sin reconstruirlo.

    Corre las mismas verificaciones que la etapa final del pipeline sobre
    un .docx ya existente (por defecto, el draft) y registra la corrida en
    `runs/`. Sale con código 1 si alguna verificación falla."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    docx_path = Path(docx) if docx else None
    result = deps.verification.verify_all(
        resolved.doc_id, resolved.template, resolved.config, docx_path=docx_path, strict=strict
    )
    result = _filter_review_dimensions(result, dimensions)
    deps.run_recorder.record(
        resolved.doc_id, resolved.config, repo_root, "verify",
        {
            "strict": strict,
            "dimensions": [dimension.value for dimension in dimensions or []],
            "passed": result.passed,
            "issues": [i.to_dict() for i in result.issues],
        },
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@core_app.command()
def history(ctx: typer.Context, limit: int = typer.Option(20, "--limit"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Lista las corridas registradas en `runs/`, de la más reciente a la más vieja."""
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    records = deps.history.list_runs(resolved.doc_id, resolved.config, limit=limit)
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
    """Imprime la marca de tiempo local ISO-8601 que usan los sellos de sección."""
    print(datetime.now().isoformat(timespec="seconds"))
