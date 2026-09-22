"""Opt-in CLI surface for the workspace-backed v2 pipeline."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from docs.application.document_pipeline import (
    _capabilities_for,
    _current_input_identities,
    _resolve_publish_inputs,
)
from docs.application.pipeline_components import PUBLIC_PIPELINES
from docs.application.provenance import ProvenanceLedger
from docs.application.visual_baseline import VisualBaselineError, VisualBaselineService
from docs.application.workspaces import WorkspaceRegistry
from docs.cli.commands.source_app import run_source_command
from docs.domain.artifacts import BuildManifest
from docs.domain.contracts import Run
from docs.domain.identity import sha256_file
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import ReviewDimension
from docs.infrastructure.locking import directory_handle_guard, owned_directory_lock
from docs.infrastructure.persistence.x20 import (
    SqliteArtifactStore,
    SqliteFindingStore,
    SqliteJobQueue,
    SqlitePassportStore,
    SqliteRunStore,
)

document_app = typer.Typer(help="Workspace-backed document engineering commands.")

_BATCH_OUTPUT_PATHS = (Path("output") / "current", Path("output") / "release")


def _source_mime_type(filename: str) -> str:
    known = {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
    }
    return known.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or "application/octet-stream"




def _promote_release_candidate(
    document_root: Path, document_id: str, *, allow_consumed_candidate: bool = False
) -> None:
    """Commit the package only after its format publication has succeeded."""
    release_dir = document_root / "output" / "release"
    candidate = release_dir / f".{document_id}.zip.candidate"
    destination = release_dir / f"{document_id}.zip"
    if not candidate.is_file() or candidate.is_symlink():
        if allow_consumed_candidate and destination.is_file() and not destination.is_symlink():
            # The publication transaction already committed this exact destination.
            # A concurrent/older final ZIP is never accepted because this path is only
            # used after the transaction has reported success.
            return
        raise RuntimeError("package-release completed without a safe release candidate")
    if any(path.is_symlink() for path in (release_dir, *release_dir.parents)):
        raise RuntimeError("release directory must not be symlinked")
    candidate_identity = os.stat(candidate, follow_symlinks=False)
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    with _package_lock(destination):
        parent_identity = _directory_identity(release_dir)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")
        current = os.stat(candidate, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            candidate_identity.st_dev,
            candidate_identity.st_ino,
            candidate_identity.st_size,
            candidate_identity.st_mtime_ns,
        ) or hashlib.sha256(candidate.read_bytes()).hexdigest() != candidate_hash:
            raise RuntimeError("release candidate changed before publication")
        with directory_handle_guard(release_dir):
            os.replace(candidate, destination)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")


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
    if command == "build" and not _batch_lock_held:
        resolved = ctx.obj["deps"].resolve_context(ctx.obj.get("doc", ""))
        root = ctx.obj["deps"].workspace.doc_root(resolved.doc_id)
        with owned_directory_lock(root / "runs" / ".x20-batch.lock"):
            return _run(ctx, command, json_output, formats, policy, dimensions, pipeline_id,
                        artifact_path, manifest_path, _batch_lock_held=True)
    selected_document = ctx.obj.get("doc", "")
    if formats is None:
        resolved = ctx.obj["deps"].resolve_context(selected_document)
        configured_format: str | None = None
        if isinstance(resolved.config, Mapping):
            output_config = resolved.config.get("output")
            if isinstance(output_config, Mapping):
                output_format = output_config.get("format")
                if isinstance(output_format, str):
                    configured_format = output_format
        requested = [configured_format or "docx"]
    else:
        requested = formats
    reports: list[dict[str, Any]] = []
    batch_backup: Path | None = None
    batch_root: Path | None = None
    batch_journal: Path | None = None
    if command == "build":
        resolved_for_backup = ctx.obj["deps"].resolve_context(selected_document)
        batch_root = ctx.obj["deps"].workspace.doc_root(resolved_for_backup.doc_id)
        batch_root.mkdir(parents=True, exist_ok=True)
        batch_journal = _batch_journal_path(batch_root)
        _recover_batch_transaction(batch_journal, _lock_held=True)
        batch_backup = Path(tempfile.mkdtemp(prefix=".x20-batch-", dir=batch_root))
        batch_paths = _BATCH_OUTPUT_PATHS
        for relative in batch_paths:
            current = batch_root / relative
            if current.exists() and not current.is_symlink():
                shutil.copytree(current, batch_backup / relative)
        _write_batch_journal(batch_journal, batch_root, batch_backup, batch_paths)
    def restore_batch() -> None:
        if batch_journal is not None:
            _recover_batch_transaction(batch_journal, _lock_held=True)
    try:
        for output_format in requested:
            selected_policy = PipelinePolicy(policy) if policy is not None else None
            provenance_run_id = f"cli-build-{output_format}-{uuid.uuid4().hex}" if command == "build" else None
            service = ctx.obj["deps"].create_document_pipeline_service(

                output_format,
                selected_policy,
                document=selected_document,
                pipeline_id=pipeline_id,
                provenance_run_id=provenance_run_id,
                artifact_path=artifact_path,
                manifest_path=manifest_path,
            )
            external_artifacts: set[str] | frozenset[str] | None = None
            if pipeline_id in {"document-package", "document-publish"}:
                # The package sub-pipeline starts from the persisted, verified
                # build boundary loaded by create_document_pipeline_service.  The package
                # service performs the artifact/manifest/provenance check;
                # these contracts only tell the runtime that the boundary is
                # intentionally supplied from the previous build.
                required = service.registry.resolve(pipeline_id).definition.external_artifacts
                if pipeline_id == "document-package":
                    external_artifacts = required
                else:
                    source_manifest = manifest_path
                    if source_manifest is None:
                        resolved = ctx.obj["deps"].resolve_context(selected_document)
                        source_artifact = (
                            resolved.config.get("paths", {}).get("output_draft_dir")
                        )
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
                        external_artifacts = {
                            record["contract"]
                            for record in records
                            if isinstance(record, Mapping) and isinstance(record.get("contract"), str)
                        }
                    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                        external_artifacts = set()
            report = service.run(
                provenance_run_id or f"cli-{command}-{output_format}",
                publish=command == "build"
                and pipeline_id in {"document", "document-publish"}
                and (selected_policy is None or selected_policy.can_publish()),
                pipeline_id=pipeline_id,
                external_artifacts=external_artifacts,
            )
            report_payload = report.to_dict()
            if dimensions:
                stage_dimensions = {
                    "editorial-review": ReviewDimension.EDITORIAL,
                    "evidence-review": ReviewDimension.EVIDENCE,
                    "consistency-review": ReviewDimension.CONSISTENCY,
                    "structural-audit": ReviewDimension.STRUCTURAL,
                    "accessibility-review": ReviewDimension.ACCESSIBILITY,
                    "visual-review": ReviewDimension.VISUAL,
                    "reproducibility-check": ReviewDimension.REPRODUCIBILITY,
                }
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
                            and stage_dimensions.get(item["stage"]) in selected
                        ]
                        report_payload["succeeded"] = all(
                            item.get("ok", False) for item in execution["results"]
                        )
                report_payload["dimensions"] = [dimension.value for dimension in dimensions]
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
                and (selected_policy is None or selected_policy.can_publish())
            ):
                resolved = ctx.obj["deps"].resolve_context(selected_document)
                _promote_release_candidate(
                    ctx.obj["deps"].workspace.doc_root(resolved.doc_id),
                    resolved.doc_id,
                    allow_consumed_candidate=True,
                )
                draft_dir = resolved.config.get("paths", {}).get("output_draft_dir")
                resolved_root = ctx.obj["deps"].workspace.doc_root(resolved.doc_id)
                if (
                    pipeline_id == "document"
                    and artifact_path is None
                    and manifest_path is None
                    and isinstance(draft_dir, str)
                ):
                    artifact = Path(draft_dir).parent / "current" / f"{resolved.doc_id}.{output_format}"
                    if artifact.is_file():
                        ledger = ProvenanceLedger(resolved_root / "runs" / "provenance.json", trusted_root=resolved_root)
                        recorded = ledger.load_attestation(provenance_run_id or "")
                        if recorded is None:
                            raise RuntimeError("missing pre-publication build attestation")
                        BuildManifest.from_dict(recorded.get("manifest", recorded))
                        manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
                        if not manifest_path.is_file():
                            raise RuntimeError("missing atomic build manifest sidecar")
                        item["manifest"] = str(manifest_path)
            if batch_journal is not None:
                _record_batch_outputs(batch_journal, resolved_for_backup.doc_id, output_format)
            reports.append(item)
    except Exception:
        # Recovery failure must leave the journal and backups for a retry.
        restore_batch()
        raise
    else:
        if batch_backup is not None and not all(item["report"].get("succeeded", False) for item in reports):
            restore_batch()
        if batch_journal is not None and batch_journal.exists():
            batch_journal.unlink()
            if batch_backup is not None:
                shutil.rmtree(batch_backup)
    payload = reports[0] if len(reports) == 1 else reports
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for item in reports:
            typer.echo(f"v2 {command} ({item['format']}): workspace integration")
            typer.echo(json.dumps(item["report"], indent=2, sort_keys=True))
    if not all(item["report"].get("succeeded", False) for item in reports):
        raise typer.Exit(code=1)


def _batch_journal_path(root: Path) -> Path:
    return root / "runs" / "x20-batch-transaction.json"


def _write_batch_journal(journal: Path, root: Path, backup: Path, paths: tuple[Path, ...]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "docs.batch/v1",
        "root": str(root.resolve()),
        "backup": str(backup.resolve()),
        "paths": [path.as_posix() for path in paths],
        "expected": {path.as_posix(): _batch_snapshot(root / path) for path in paths},
        "saved": {path.as_posix(): _batch_snapshot(backup / path) for path in paths},
    }
    temporary = journal.with_name(f".{journal.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, journal)


def _batch_snapshot(directory: Path) -> dict[str, list[object]]:
    if any(path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_reparse_tag", 0) != 0) for path in (directory, *directory.parents)):
        raise RuntimeError("batch recovery refuses redirected paths")
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise RuntimeError("batch recovery output path must be a directory")
    snapshot: dict[str, list[object]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_reparse_tag", 0) != 0):
            raise RuntimeError("batch recovery refuses redirected paths")
        if path.is_file():
            identity = path.stat()
            snapshot[path.relative_to(directory).as_posix()] = [
                sha256_file(path), identity.st_dev, identity.st_ino,
                identity.st_size, identity.st_mtime_ns, identity.st_ctime_ns,
            ]
        elif not path.is_dir():
            raise RuntimeError("batch recovery refuses non-regular paths")
    return snapshot


def _record_batch_outputs(journal: Path, doc_id: str, output_format: str) -> None:
    """Record only the known publication paths, never adopt unrelated outputs.

    A crash before this checkpoint fails closed: publication ownership cannot
    be inferred from a current batch journal or from unrecorded output bytes.
    """
    payload = json.loads(journal.read_text(encoding="utf-8"))
    owned = {
        "output/current": (f"{doc_id}.{output_format}", f"{doc_id}.{output_format}.manifest.json"),
        "output/release": (f"{doc_id}.zip",),
    }
    for relative, names in owned.items():
        current = _batch_snapshot(Path(payload["root"]) / relative)
        for name in names:
            if name in current:
                payload["expected"][relative][name] = current[name]
    temporary = journal.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, journal)


def _recover_batch_transaction(journal: Path, *, _lock_held: bool = False) -> None:
    if not journal.exists():
        return
    if not _lock_held:
        with owned_directory_lock(journal.parent / ".x20-batch.lock"):
            return _recover_batch_transaction(journal, _lock_held=True)
    payload = json.loads(journal.read_text(encoding="utf-8"))
    root = journal.parent.parent.resolve()
    backup = Path(payload["backup"])
    paths = _BATCH_OUTPUT_PATHS
    if (Path(payload["root"]).resolve() != root
            or journal.resolve() != _batch_journal_path(root)
            or backup.parent.resolve() != root or not backup.name.startswith(".x20-batch-")
            or payload.get("paths") != [path.as_posix() for path in paths]):
        raise RuntimeError("batch recovery path scope is invalid")
    if not isinstance(payload.get("expected"), dict) or not isinstance(payload.get("saved"), dict):
        raise RuntimeError("batch recovery ownership unavailable; preserve journal for manual recovery")
    _batch_snapshot(backup)  # Validate all backup paths before touching any output.

    def checked_snapshot(relative: Path) -> dict[str, list[object]]:
        key = relative.as_posix()
        current = _batch_snapshot(root / relative)
        expected = payload["expected"][key]
        saved = payload["saved"][key]
        for name in current.keys() | expected.keys() | saved.keys():
            value = current.get(name)
            previous = saved.get(name)
            if value == expected.get(name) or (value is not None and previous is not None and value[0] == previous[0]):
                continue
            if value is None and previous is None:  # Already removed on a previous recovery attempt.
                continue
            raise RuntimeError(f"batch recovery output changed concurrently: {relative / name}")
        return current

    for relative in paths:
        if _batch_snapshot(backup / relative) != payload["saved"][relative.as_posix()]:
            raise RuntimeError("batch recovery backup changed")
        checked_snapshot(relative)
    # Copy first. A failed copy never removes a live output or consumes backups.
    with tempfile.TemporaryDirectory(prefix=".x20-batch-restore-", dir=root) as temporary:
        staged = Path(temporary)
        for relative in paths:
            saved_dir = backup / relative
            if saved_dir.exists():
                shutil.copytree(saved_dir, staged / relative)
        for relative in paths:
            current = checked_snapshot(relative)
            saved = payload["saved"][relative.as_posix()]
            for name in sorted(current.keys() | saved.keys()):
                checked_snapshot(relative)
                target = root / relative / name
                if name in saved:
                    if name in current and current[name][0] == saved[name][0]:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with directory_handle_guard(target.parent):
                        os.replace(staged / relative / name, target)
                else:
                    target.unlink(missing_ok=True)
    # Only a fully restored transaction can retire its recovery evidence.
    journal.unlink()
    shutil.rmtree(backup)


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
    queue_path = deps.workspace.doc_root(resolved.doc_id) / "inbox" / "_classification-queue.json"
    if not queue_path.is_file():
        raise typer.BadParameter("classification queue is unavailable; run document ingest first")
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    entries = queue if isinstance(queue, list) else queue.get("items", queue.get("sources", []))
    if relative_path is not None or role is not None:
        if not relative_path or role not in {"evidence", "example", "normative"}:
            raise typer.BadParameter("--file and --role are required; role must be evidence, example, or normative")
        entry = next((item for item in entries if str(item.get("relative_path")) == relative_path), None)
        if entry is None:
            raise typer.BadParameter("source is not present in the classification queue")
        entry["confirmed_role"] = role
        queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    capability_registry = _capabilities_for(
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
        "unsupported_stages": (dict(current_v2).get("unsupported_stages", []) if isinstance(current_v2, Mapping) else []),
        "publication_blockers": (dict(current_v2).get("publication_blockers", []) if isinstance(current_v2, Mapping) else []),
        "public_pipelines": [spec.pipeline_id for spec in PUBLIC_PIPELINES],
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
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
    if async_run:
        if len(formats or ["docx"]) != 1:
            raise typer.BadParameter("--async supports exactly one --format")
        deps = ctx.obj["deps"]
        resolved = deps.resolve_context(ctx.obj.get("doc", ""))
        workspace_root = deps.workspace.documents_dir.parent.resolve()
        registry_path = workspace_root / ".docs" / "workspaces.json"
        # A document configured by this cwd must never fall back to the
        # process-wide active workspace. That fallback can enqueue a run for a
        # different project and makes the detached worker fail against the
        # wrong document. Use the workspace-local registry unless the caller
        # explicitly supplied DOCS_WORKSPACE_REGISTRY.
        registry = WorkspaceRegistry(
            registry_path if registry_path.is_file() else os.environ.get("DOCS_WORKSPACE_REGISTRY") or (Path.home() / ".docs" / "workspaces.json")
        )
        active = registry.active()
        if active is None:
            raise typer.BadParameter("No workspace is selected; run docs workspace use <id> first")
        workspace_root = Path(str(active["root"])).resolve()
        state = workspace_root / ".docs" / "x20.sqlite3"
        run_id = str(uuid.uuid4())
        payload = {
            "run_id": run_id,
            "document_id": resolved.doc_id,
            "workspace_id": active["id"],
            "pipeline_id": "document",
            "format": (formats or ["docx"])[0],
            "policy": selected_policy.value,
        }
        SqliteRunStore(state).put(Run(run_id, payload=payload, created_at=datetime.now(UTC).isoformat()))
        SqliteJobQueue(state).enqueue(run_id, payload)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        worker_env = os.environ.copy()
        source_root = Path(__file__).resolve().parents[4]
        worker_env["PYTHONPATH"] = os.pathsep.join(
            part for part in (os.fspath(source_root), worker_env.get("PYTHONPATH")) if part
        )
        worker_log = workspace_root / ".docs" / "worker.log"
        # Windows keeps redirected handles alive across a detached process
        # boundary more aggressively than POSIX. The durable run/passport is
        # the authoritative structured record; avoid holding the workspace
        # log open after the worker exits so temporary workspaces and clean
        # shutdowns are actually removable. POSIX keeps the diagnostic file.
        worker_output = subprocess.DEVNULL if os.name == "nt" else worker_log.open("ab")
        subprocess.Popen(
            [os.fspath(Path(os.sys.executable)), "-m", "docs.local_worker", "--workspace-root", os.fspath(workspace_root)],
            cwd=os.fspath(workspace_root),
            stdin=subprocess.DEVNULL,
            stdout=worker_output,
            stderr=worker_output,
            env=worker_env,
            # The worker is intentionally detached from the CLI, but it must
            # not inherit unrelated descriptors (especially on Windows). An
            # inherited log handle keeps temporary workspaces locked after a
            # successful run and makes clean shutdown impossible.
            close_fds=True,
            creationflags=creationflags,
            start_new_session=True,
        )
        if hasattr(worker_output, "close"):
            worker_output.close()
        if watch:
            import time
            store = SqliteRunStore(state)
            while True:
                item = store.get(run_id)
                if item is None:
                    raise typer.BadParameter(f"Run disappeared: {run_id}")
                if item.status in {"succeeded", "completed", "failed", "cancelled", "expired"}:
                    break
                time.sleep(0.25)
        result = {"id": run_id, "status": SqliteRunStore(state).get(run_id).status if SqliteRunStore(state).get(run_id) else "queued"}
        typer.echo(json.dumps(result, sort_keys=True) if json_output else f"{run_id}\t{result['status']}")
        return
    # Synchronous execution uses the same durable worker path as async runs.
    # This keeps the CLI's two modes semantically identical: both create a
    # real Run, execute the real pipeline, and persist passport/evidence.
    if len(formats or ["docx"]) != 1:
        raise typer.BadParameter("--sync supports exactly one --format")
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    workspace_root = deps.workspace.documents_dir.parent.resolve()
    registry_path = workspace_root / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(
        registry_path if registry_path.is_file() else os.environ.get("DOCS_WORKSPACE_REGISTRY") or (Path.home() / ".docs" / "workspaces.json")
    )
    active = registry.active()
    if active is None:
        raise typer.BadParameter("No workspace is selected; run docs workspace use <id> first")
    workspace_root = Path(str(active["root"])).resolve()
    state = workspace_root / ".docs" / "x20.sqlite3"
    run_id = str(uuid.uuid4())
    payload = {
        "run_id": run_id,
        "document_id": resolved.doc_id,
        "workspace_id": active["id"],
        "pipeline_id": "document",
        "format": (formats or ["docx"])[0],
        "policy": selected_policy.value,
    }
    SqliteRunStore(state).put(Run(run_id, payload=payload, created_at=datetime.now(UTC).isoformat()))
    SqliteJobQueue(state).enqueue(run_id, payload)
    # Import lazily to avoid making the CLI composition root depend on the
    # sidecar at import time; the worker composition remains the single
    # implementation of execution and evidence finalization.
    from docs.infrastructure.persistence.x20 import (
        SqliteFindingStore,
        SqlitePublicationStore,
    )
    from docs.sidecar import _build_worker

    worker = _build_worker(
        workspace_root,
        SqliteJobQueue(state),
        state,
        SqliteRunStore(state),
        SqlitePassportStore(state),
        SqliteArtifactStore(state),
        SqliteFindingStore(state),
        SqlitePublicationStore(state),
    )
    result = worker.run_once()
    if result is None:
        raise typer.BadParameter(f"Unable to claim synchronous run: {run_id}")
    final = SqliteRunStore(state).get(run_id)
    status = final.status if final is not None else result.state
    output = {"id": run_id, "status": status}
    typer.echo(json.dumps(output, sort_keys=True) if json_output else f"{run_id}\t{status}")


def _durable_evidence_stores(ctx: typer.Context):
    deps = ctx.obj["deps"]
    root = deps.workspace.documents_dir.parent.resolve()
    registry_path = root / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(
        registry_path if registry_path.is_file() else os.environ.get("DOCS_WORKSPACE_REGISTRY") or (Path.home() / ".docs" / "workspaces.json")
    )
    active = registry.active()
    if active is not None:
        root = Path(str(active["root"])).resolve()
    state = root / ".docs" / "x20.sqlite3"
    return SqlitePassportStore(state), SqliteArtifactStore(state), SqliteFindingStore(state)


@document_app.command("passport")
def document_passport(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show the immutable evidence passport for a durable run."""
    passport_store, _, _ = _durable_evidence_stores(ctx)
    passport = passport_store.get(run_id)
    if passport is None:
        raise typer.BadParameter(f"Passport not found for run: {run_id}")
    payload = passport.to_dict()
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_output else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@document_app.command("evidence")
def document_evidence(ctx: typer.Context, run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show the passport and all findings/artifacts produced by a durable run."""
    passport_store, artifact_store, finding_store = _durable_evidence_stores(ctx)
    passport = passport_store.get(run_id)
    if passport is None:
        raise typer.BadParameter(f"Evidence not found for run: {run_id}")
    payload = {
        "passport": passport.to_dict(),
        "artifacts": [item.to_dict() for item in artifact_store.list_for_run(run_id)],
        "findings": finding_store.list_for_run(run_id),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_output else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
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
        registered = service.registry.resolve(pipeline_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    definition = registered.definition
    payload = {
        "pipeline_id": pipeline_id,
        "stages": list(definition.plan()),
        "external_artifacts": sorted(definition.external_artifacts),
        "contracts": [contract.to_dict() for contract in definition.artifacts],
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
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


def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise typer.BadParameter(f"package output parent changed during {operation}: {path}")


@contextmanager
def _package_lock(output: Path):
    """Serialize existing release-package merge and publication transactions."""
    with owned_directory_lock(output.with_name(output.name + ".lock")):
        yield


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
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_output else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


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
        result = publication_service.publish(
            prepared, current_identities=current
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "published": True,
        "artifact": _artifact_payload(ctx, result.artifact),
        "manifest": str(result.manifest.resolve()),
        "warnings": list(result.warnings),
    }
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))
