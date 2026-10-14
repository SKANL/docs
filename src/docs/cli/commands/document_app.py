"""Opt-in CLI surface for the workspace-backed v2 pipeline."""

from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer

from docs.application.classification_queue import (
    ClassificationQueueError,
    review_classification_queue,
)
from docs.application.document_pipeline import (
    _current_input_identities,
    _resolve_publish_inputs,
)
from docs.application.pipeline_plan import describe_pipeline
from docs.application.pipeline_registry import PUBLIC_PIPELINES
from docs.application.pipeline_service import PipelineRequest
from docs.application.visual_baseline import VisualBaselineError, VisualBaselineService
from docs.cli.commands.document_batch import BatchTransaction
from docs.cli.commands.document_release import promote_release_candidate
from docs.cli.commands.document_run import (
    durable_evidence_stores,
    queue_run,
    run_inline,
    run_status,
    spawn_detached_worker,
    wait_for_run,
)
from docs.cli.commands.source_app import run_source_command
from docs.composition import owned_directory_lock
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import pretty_json, sha256_file
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import ReviewDimension

document_app = typer.Typer(help="Workspace-backed document engineering commands.")

_STAGE_DIMENSIONS = {
    "editorial-review": ReviewDimension.EDITORIAL,
    "evidence-review": ReviewDimension.EVIDENCE,
    "consistency-review": ReviewDimension.CONSISTENCY,
    "structural-audit": ReviewDimension.STRUCTURAL,
    "accessibility-review": ReviewDimension.ACCESSIBILITY,
    "visual-review": ReviewDimension.VISUAL,
    "reproducibility-check": ReviewDimension.REPRODUCIBILITY,
}


def _source_mime_type(filename: str) -> str:
    known = {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
    }
    return known.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _requested_formats(ctx: typer.Context, formats: list[str] | None) -> list[str]:
    if formats is not None:
        return formats
    resolved = ctx.obj["deps"].resolve_context(ctx.obj.get("doc", ""))
    configured_format: str | None = None
    if isinstance(resolved.config, Mapping):
        output_config = resolved.config.get("output")
        if isinstance(output_config, Mapping):
            output_format = output_config.get("format")
            if isinstance(output_format, str):
                configured_format = output_format
    return [configured_format or "docx"]


def _boundary_external_artifacts(
    ctx: typer.Context,
    service: Any,
    pipeline_id: str,
    output_format: str,
    manifest_path: Path | None,
) -> set[str] | frozenset[str] | None:
    """Contracts a package/publish run starts from instead of recomputing.

    The package sub-pipeline starts from the persisted, verified build boundary
    loaded by create_document_pipeline_service.  The package service performs
    the artifact/manifest/provenance check; these contracts only tell the
    runtime that the boundary is intentionally supplied from the previous build.
    """
    if pipeline_id not in {"document-package", "document-publish"}:
        return None
    required = service.registry.resolve(pipeline_id).definition.external_artifacts
    if pipeline_id == "document-package":
        return required
    source_manifest = manifest_path
    if source_manifest is None:
        resolved = ctx.obj["deps"].resolve_context(ctx.obj.get("doc", ""))
        source_artifact = resolved.config.get("paths", {}).get("output_draft_dir")
        source_manifest = (
            Path(source_artifact).parent / "current" / f"{resolved.doc_id}.{output_format}.manifest.json"
            if isinstance(source_artifact, str)
            else None
        )
    try:
        if source_manifest is None:
            raise ValueError("publish manifest is unavailable")
        manifest_data = json.loads(source_manifest.read_text(encoding="utf-8"))
        records = manifest_data.get("verification", {}).get("stage_artifacts", [])
        return {
            record["contract"]
            for record in records
            if isinstance(record, Mapping) and isinstance(record.get("contract"), str)
        }
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return set()


def _restrict_to_dimensions(report_payload: dict[str, Any], dimensions: list[ReviewDimension]) -> None:
    """Keep only the review stages of the requested dimensions, in place."""
    selected = set(dimensions)
    execution = report_payload.get("execution")
    if isinstance(execution, dict):
        results = execution.get("results", [])
        if isinstance(results, list):
            execution["results"] = [
                item
                for item in results
                if isinstance(item, dict)
                and isinstance(item.get("stage"), str)
                and _STAGE_DIMENSIONS.get(item["stage"]) in selected
            ]
            report_payload["succeeded"] = all(item.get("ok", False) for item in execution["results"])
    report_payload["dimensions"] = [dimension.value for dimension in dimensions]


def _promote_published_build(
    ctx: typer.Context,
    item: dict[str, Any],
    *,
    pipeline_id: str,
    output_format: str,
    provenance_run_id: str | None,
    artifact_path: Path | None,
    manifest_path: Path | None,
) -> Path | None:
    """Promote the release candidate of a successful build; return the attested manifest, if any."""
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    resolved_root = deps.workspace.doc_root(resolved.doc_id)
    promote_release_candidate(resolved_root, resolved.doc_id, allow_consumed_candidate=True)
    draft_dir = resolved.config.get("paths", {}).get("output_draft_dir")
    if not (
        pipeline_id == "document"
        and artifact_path is None
        and manifest_path is None
        and isinstance(draft_dir, str)
    ):
        return None
    artifact = Path(draft_dir).parent / "current" / f"{resolved.doc_id}.{output_format}"
    if not artifact.is_file():
        return None
    ledger = deps.provenance_ledger(resolved_root / "runs" / "provenance.json", trusted_root=resolved_root)
    recorded = ledger.load_attestation(provenance_run_id or "")
    if recorded is None:
        raise RuntimeError("missing pre-publication build attestation")
    BuildManifest.from_dict(recorded.get("manifest", recorded))
    attested = artifact.with_suffix(artifact.suffix + ".manifest.json")
    if not attested.is_file():
        raise RuntimeError("missing atomic build manifest sidecar")
    item["manifest"] = str(attested)
    return attested


def _run_format(
    ctx: typer.Context,
    command: str,
    output_format: str,
    policy: PipelineMode | None,
    dimensions: list[ReviewDimension] | None,
    pipeline_id: str,
    artifact_path: Path | None,
    manifest_path: Path | None,
) -> tuple[dict[str, Any], Path | None]:
    """Execute the pipeline for one format; return its report item and the manifest path to carry forward."""
    selected_policy = PipelinePolicy(policy) if policy is not None else None
    can_publish = selected_policy is None or selected_policy.can_publish()
    provenance_run_id = f"cli-build-{output_format}-{uuid.uuid4().hex}" if command == "build" else None
    service = ctx.obj["deps"].create_document_pipeline_service(
        output_format,
        selected_policy,
        document=ctx.obj.get("doc", ""),
        pipeline_id=pipeline_id,
        provenance_run_id=provenance_run_id,
        artifact_path=artifact_path,
        manifest_path=manifest_path,
    )
    external_artifacts = _boundary_external_artifacts(ctx, service, pipeline_id, output_format, manifest_path)
    report = service.execute(
        PipelineRequest(
            run_id=provenance_run_id or f"cli-{command}-{output_format}",
            publish=command == "build" and pipeline_id in {"document", "document-publish"} and can_publish,
            pipeline_id=pipeline_id,
            external_artifacts=(tuple(external_artifacts) if external_artifacts is not None else None),
        )
    )
    report_payload = report.to_dict()
    if dimensions:
        _restrict_to_dimensions(report_payload, dimensions)
    item: dict[str, Any] = {
        "command": command,
        "integration": "workspace",
        "format": output_format,
        "report": report_payload,
    }
    if (
        command == "build"
        and pipeline_id in {"document", "document-publish", "document-package"}
        and bool(report_payload.get("succeeded"))
        and can_publish
    ):
        attested = _promote_published_build(
            ctx,
            item,
            pipeline_id=pipeline_id,
            output_format=output_format,
            provenance_run_id=provenance_run_id,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
        )
        manifest_path = attested or manifest_path
    return item, manifest_path


def _report_results(command: str, reports: list[dict[str, Any]], json_output: bool) -> None:
    payload = reports[0] if len(reports) == 1 else reports
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for item in reports:
            typer.echo(f"v2 {command} ({item['format']}): workspace integration")
            typer.echo(json.dumps(item["report"], indent=2, sort_keys=True))
    if not all(item["report"].get("succeeded", False) for item in reports):
        raise typer.Exit(code=1)


def _run(
    ctx: typer.Context,
    command: str,
    json_output: bool,
    formats: list[str] | None,
    policy: PipelineMode | None,
    dimensions: list[ReviewDimension] | None = None,
    pipeline_id: str = "document",
    artifact_path: Path | None = None,
    manifest_path: Path | None = None,
    _batch_lock_held: bool = False,
) -> None:
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", "")) if command == "build" else None
    if resolved is not None and not _batch_lock_held:
        root = deps.workspace.doc_root(resolved.doc_id)
        with owned_directory_lock(root / "runs" / ".docs-batch.lock"):
            return _run(
                ctx,
                command,
                json_output,
                formats,
                policy,
                dimensions,
                pipeline_id,
                artifact_path,
                manifest_path,
                _batch_lock_held=True,
            )
    requested = _requested_formats(ctx, formats)
    transaction = (
        BatchTransaction.begin(resolved.doc_id, deps.workspace.doc_root(resolved.doc_id))
        if resolved is not None
        else None
    )
    reports: list[dict[str, Any]] = []
    try:
        for output_format in requested:
            item, manifest_path = _run_format(
                ctx, command, output_format, policy, dimensions, pipeline_id, artifact_path, manifest_path
            )
            if transaction is not None:
                transaction.record(output_format)
            reports.append(item)
    except Exception:
        # Recovery failure must leave the journal and backups for a retry.
        if transaction is not None:
            transaction.restore()
        raise
    else:
        if transaction is not None:
            transaction.finish(succeeded=all(item["report"].get("succeeded", False) for item in reports))
    _report_results(command, reports, json_output)


@document_app.command("release")
def release(
    ctx: typer.Context,
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode = typer.Option(PipelineMode.release, "--policy"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Execute the complete verified release pipeline for the active document."""
    _run(
        ctx,
        "build",
        json_output,
        formats,
        policy,
        pipeline_id="document",
    )


@document_app.command("ingest")
def ingest(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Ingest document sources through the native v2 source stage."""
    run_source_command(ctx, "ingest", json_output)


@document_app.command("classify")
def classify(
    ctx: typer.Context,
    relative_path: str | None = typer.Option(None, "--file"),
    role: str | None = typer.Option(None, "--role"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect or confirm source roles in the real ingest classification queue."""
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    try:
        entries = review_classification_queue(deps.workspace.doc_root(resolved.doc_id), relative_path, role)
    except ClassificationQueueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = {"document_id": resolved.doc_id, "items": entries}
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":") if json_output else None))


@document_app.command("import")
def import_source(
    ctx: typer.Context,
    source: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Copy a source into the active document inbox with a content hash."""
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    inbox = deps.workspace.doc_root(resolved.doc_id) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(source)
    destination = inbox / f"{digest[:12]}-{source.name}"
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    payload = {
        "document_id": resolved.doc_id,
        "filename": source.name,
        "path": str(destination),
        "sha256": digest,
        "size": destination.stat().st_size,
        "mime_type": _source_mime_type(source.name),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=None if json_output else 2, sort_keys=True))


@document_app.command("prepare")
def prepare(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Ingest, normalize, and compile the document source structure."""
    run_source_command(ctx, "prepare", json_output)


@document_app.command("status")
def status(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Report domain status, including v2 manifest and provenance details."""
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    result = deps.status.status_summary(
        resolved.doc_id,
        resolved.template,
        resolved.config,
        normative=resolve_normative_settings(resolved.config),
    )
    payload = result.to_dict()
    output = resolved.config.get("output", {})
    output_format = output.get("format", "docx") if isinstance(output, Mapping) else "docx"
    renderer = deps.resolve_renderer(resolved.config)
    capability_registry = deps.create_capability_registry(
        renderer,
        output_format,
        deps.workspace.doc_root(resolved.doc_id),
        resolved.config.get("paths", {}),
    )
    current_v2 = payload.get("v2", {})
    payload["v2"] = {
        **(dict(current_v2) if isinstance(current_v2, Mapping) else {}),
        "capabilities": capability_registry.report(),
        "capability_diagnostics": capability_registry.diagnostics(),
        "unsupported_stages": (
            dict(current_v2).get("unsupported_stages", []) if isinstance(current_v2, Mapping) else []
        ),
        "publication_blockers": (
            dict(current_v2).get("publication_blockers", []) if isinstance(current_v2, Mapping) else []
        ),
        "public_pipelines": [spec.pipeline_id for spec in PUBLIC_PIPELINES],
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else pretty_json(payload)
    )


@document_app.command("run")
def run_document(
    ctx: typer.Context,
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode | None = typer.Option(None, "--policy"),
    strict: bool = typer.Option(False, "--strict", help="Run with strict verification policy."),
    release: bool = typer.Option(False, "--release", help="Run with release policy and publication checks."),
    async_run: bool = typer.Option(False, "--async", help="Queue the run and process it with a detached local worker."),
    sync: bool = typer.Option(False, "--sync", help="Run synchronously in the current process (the default)."),
    watch: bool = typer.Option(False, "--watch", help="Wait for a queued asynchronous run to finish."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Execute the real document pipeline synchronously from source to verified output.

    This is the CLI's end-to-end entry point. It intentionally delegates to
    the same application pipeline used by build/release instead of creating a
    second implementation or returning a synthetic run result.
    """
    if strict and release:
        raise typer.BadParameter("--strict and --release are mutually exclusive")
    if async_run and sync:
        raise typer.BadParameter("--async and --sync are mutually exclusive")
    selected_policy = policy or (PipelineMode.strict if strict else PipelineMode.release)
    if watch and not async_run:
        raise typer.BadParameter("--watch requires --async")
    if len(formats or ["docx"]) != 1:
        raise typer.BadParameter("--async supports exactly one --format" if async_run else "--sync supports exactly one --format")
    # Both modes create a real Run and execute the real pipeline through the
    # durable worker, so passport/evidence are persisted identically.
    queued = queue_run(ctx.obj["deps"], ctx.obj.get("doc", ""), (formats or ["docx"])[0], selected_policy)
    if async_run:
        spawn_detached_worker(queued.workspace_root)
        if watch:
            wait_for_run(queued)
        status = run_status(queued, "queued")
    else:
        status = run_inline(queued)
    typer.echo(
        json.dumps({"id": queued.run_id, "status": status}, sort_keys=True)
        if json_output
        else f"{queued.run_id}\t{status}"
    )


@document_app.command("passport")
def document_passport(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show the immutable evidence passport for a durable run."""
    passport_store = durable_evidence_stores(ctx.obj["deps"]).passports
    passport = passport_store.get(run_id)
    if passport is None:
        raise typer.BadParameter(f"Passport not found for run: {run_id}")
    payload = passport.to_dict()
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if json_output
        else pretty_json(payload)
    )


@document_app.command("evidence")
def document_evidence(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show the passport and all findings/artifacts produced by a durable run."""
    stores = durable_evidence_stores(ctx.obj["deps"])
    passport = stores.passports.get(run_id)
    if passport is None:
        raise typer.BadParameter(f"Evidence not found for run: {run_id}")
    payload = {
        "passport": passport.to_dict(),
        "artifacts": [item.to_dict() for item in stores.artifacts.list_for_run(run_id)],
        "findings": stores.findings.list_for_run(run_id),
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if json_output
        else pretty_json(payload)
    )


@document_app.command("plan")
def plan(
    ctx: typer.Context,
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to inspect."),
    output_format: str = typer.Option("docx", "--format"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the ordered stages and external contracts of a registered pipeline."""
    deps = ctx.obj["deps"]
    service = deps.create_document_pipeline_service(
        output_format, document=ctx.obj.get("doc", ""), pipeline_id=pipeline_id
    )
    try:
        payload = describe_pipeline(service, pipeline_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else pretty_json(payload)
    )


@document_app.command("build")
def build(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode | None = typer.Option(None, "--policy"),
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to execute."),
    artifact: Path | None = typer.Option(None, "--artifact", help="Verified existing artifact for publish/package."),
    manifest: Path | None = typer.Option(None, "--manifest", help="Verified existing manifest for publish/package."),
) -> None:
    """Build verified artifacts in one or more requested formats."""
    _run(
        ctx,
        "build",
        json_output,
        formats,
        policy,
        pipeline_id=pipeline_id,
        artifact_path=artifact,
        manifest_path=manifest,
    )


@document_app.command("verify")
def verify(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode | None = typer.Option(None, "--policy"),
    dimensions: list[ReviewDimension] | None = typer.Option(None, "--dimension"),
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to execute."),
) -> None:
    """Verify artifacts without publishing them."""
    _run(ctx, "verify", json_output, formats, policy, dimensions, pipeline_id)


def _artifact_payload(ctx: typer.Context, path: Path) -> dict[str, object]:
    return ctx.obj["deps"].artifact_reports.inspect(path)


@document_app.command("baseline")
def baseline(
    source_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    destination_dir: Path = typer.Option(..., "--destination", "-d", file_okay=False),
    update: bool = typer.Option(False, "--update", help="Replace an existing baseline explicitly."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Explicitly snapshot rendered PNG previews as a visual baseline."""
    try:
        published = VisualBaselineService().update(source_dir, destination_dir, overwrite=update)
    except VisualBaselineError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "source": str(source_dir.resolve()),
        "destination": str(destination_dir.resolve()),
        "updated": update,
        "pages": [str(path.resolve()) for path in published],
    }
    typer.echo(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, indent=2, sort_keys=True)
    )


@document_app.command("inspect")
def inspect(
    ctx: typer.Context,
    artifact: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an artifact identity without modifying it."""
    payload = _artifact_payload(ctx, artifact)
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))


@document_app.command("diff")
def diff(
    ctx: typer.Context,
    left: Path = typer.Argument(..., exists=True, readable=True),
    right: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two derived artifacts by identity and readable text when available."""
    payload = ctx.obj["deps"].artifact_reports.compare(left, right)
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if json_output
        else pretty_json(payload)
    )


@document_app.command("package")
def package(
    ctx: typer.Context,
    source_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Package verified derived artifacts atomically as a ZIP archive."""
    try:
        ctx.obj["deps"].package_publications.package(output, source_dir)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {"path": str(output.resolve()), "artifact": _artifact_payload(ctx, output)}
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))


@document_app.command("publish")
def publish(
    ctx: typer.Context,
    source: Path = typer.Argument(..., exists=True, readable=True),
    destination: Path = typer.Argument(...),
    policy: PipelineMode = typer.Option(PipelineMode.release, "--policy"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Publish one verified artifact only under a policy that permits release."""
    publication_service = ctx.obj["deps"].package_publications
    try:
        prepared = publication_service.preflight_publish(source, destination, policy=policy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    document_root = source.parent.parent.parent
    output_format = source.suffix.removeprefix(".")
    try:
        resolved, config, renderer = _resolve_publish_inputs(ctx.obj["deps"], document_root, output_format)
        current = _current_input_identities(
            resolved=resolved,
            config=config,
            renderer=renderer,
            root=document_root,
            output_format=output_format,
        )
    except Exception as exc:
        raise typer.BadParameter(f"publish requires resolvable current inputs: {exc}") from exc
    try:
        result = publication_service.publish(prepared, current_identities=current)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "published": True,
        "artifact": _artifact_payload(ctx, result.artifact),
        "manifest": str(result.manifest.resolve()),
        "warnings": list(result.warnings),
    }
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))
