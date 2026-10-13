"""The sidecar's local worker process: runs queued document pipelines."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docs.application.pipeline_service import PipelineRequest
from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from docs.composition import compose_application, open_workspace_registry
from docs.domain.identity import sha256_bytes, sha256_file
from docs.domain.runtime_records import Artifact, Passport, Run
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.sqlite_runtime import SqliteLeaseStore
from docs.sidecar.stores import WorkspaceEvidenceStores, WorkspaceJobQueue, WorkspaceRunStore
from docs.workers.composition import compose_worker
from docs.workers.runner import WorkerRunner


def worker_process_main(workspace: Path) -> None:
    root = Path(workspace).resolve()
    registry = open_workspace_registry(root / ".docs" / "workspaces.json")
    state_path = root / ".docs" / "runtime.sqlite3"
    queue = WorkspaceJobQueue(registry, root)
    run_store = WorkspaceRunStore(registry, root)
    evidence = WorkspaceEvidenceStores(registry, run_store, root)
    runner = build_worker(
        root,
        queue,
        state_path,
        run_store,
        evidence.passport(),
        evidence.artifact(),
        evidence.finding(),
        evidence.publication(),
    )
    runner.run_until_stopped()


class LocalRunExecutor:
    """Executes one queued run's document pipeline against the real workspace."""

    def __init__(
        self,
        pipeline_id: str,
        *,
        root: Path,
        registry: WorkspaceRegistry,
        run_store: Any,
        publication_store: Any,
        job_payloads: dict[str, dict[str, Any]],
    ) -> None:
        self.pipeline_id = pipeline_id
        self._root = root
        self._registry = registry
        self._run_store = run_store
        self._publication_store = publication_store
        self._job_payloads = job_payloads

    def run(self, run_id: str, *, inputs=(), outputs=(), excluded_stages=frozenset(), external_artifacts=None):
        del outputs, excluded_stages
        # The API payload is deliberately explicit: a run cannot execute
        # against an implicit or fake document.
        payload = self._job_payloads.get(run_id, {})
        document_id = payload.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("document_id is required to execute a run")
        output_format = payload.get("format", "docx")
        workspace_id = payload.get("workspace_id")
        run_root = self._run_root(workspace_id)

        progress = self._progress_reporter(run_id, payload)
        progress("prepare", 10)
        deps = compose_application(Workspace(run_root / "documents", run_root / "templates"))
        self._prepare_sources(deps, document_id)
        progress("pipeline", 35)
        service = deps.create_document_pipeline_service(
            output_format=output_format,
            document=document_id,
            pipeline_id=self.pipeline_id,
            provenance_run_id=run_id,
        )
        policy = str(payload.get("policy", "release"))
        report = service.execute(
            PipelineRequest(
                run_id=run_id,
                inputs=tuple(inputs),
                publish=policy != "draft",
                pipeline_id=self.pipeline_id,
                external_artifacts=(tuple(external_artifacts) if external_artifacts is not None else None),
            )
        )
        progress("finalize", 90)
        if not getattr(report, "succeeded", False):
            raise RuntimeError("document pipeline failed; inspect run evidence for stage findings")
        if self.pipeline_id == "document-publish":
            self._record_publication(run_id, document_id, workspace_id, payload)
        return {
            "pipeline_id": self.pipeline_id,
            "document_id": document_id,
            "succeeded": True,
            "report": report.to_dict(),
        }

    def _run_root(self, workspace_id: object) -> Path:
        if not (isinstance(workspace_id, str) and workspace_id):
            return self._root
        try:
            selected = self._registry.resolve(workspace_id)
        except WorkspaceRegistryError:
            # A CLI worker may use the user-level registry while the
            # durable queue lives inside the workspace. The worker is
            # already scoped to ``root``; never resolve an arbitrary
            # payload path, but allow that registered identity to be
            # processed in the current worker boundary.
            return self._root
        return Path(str(selected["root"])).resolve()

    def _progress_reporter(self, run_id: str, payload: dict[str, Any]) -> Any:
        def progress(stage: str, percent: int) -> None:
            existing = self._run_store.get(run_id)
            self._run_store.put(
                Run(
                    run_id,
                    status="running",
                    payload={**payload, "progress": {"stage": stage, "percent": percent}},
                    created_at=existing.created_at if existing is not None else "",
                )
            )

        return progress

    @staticmethod
    def _prepare_sources(deps: Any, document_id: str) -> None:
        source_pipeline = deps.create_source_pipeline()
        prepared = source_pipeline.prepare(
            document_id, deps.workspace.doc_root(document_id), deps.resolve_context(document_id).config
        )
        if not prepared.get("succeeded", False):
            raise RuntimeError("document preparation failed; inspect intake evidence")
        resolved = deps.resolve_context(document_id)
        for section in resolved.template.sections:
            deps.section.build_section(document_id, resolved.template, section.id, resolved.config)

    def _record_publication(
        self, run_id: str, document_id: str, workspace_id: object, payload: dict[str, Any]
    ) -> None:
        self._publication_store.put(
            {
                "id": run_id,
                "run_id": run_id,
                "document_id": document_id,
                "workspace_id": workspace_id,
                "environment": str(payload.get("environment", "local")),
                "artifact": document_id,
                "published_at": datetime.now(UTC).isoformat(),
                "approver": str(payload.get("approver", "local-worker")),
                "status": "passed",
            }
        )


def build_worker(
    workspace: Path,
    queue: Any,
    state_path: Path,
    run_store: Any,
    passport_store: Any,
    artifact_store: Any,
    findings_store: Any,
    publication_store: Any,
) -> WorkerRunner:
    """Compose the real local worker; no synthetic completion path is allowed."""
    root = workspace.resolve()
    registry = open_workspace_registry(root / ".docs" / "workspaces.json")
    job_payloads: dict[str, dict[str, Any]] = {}

    def executor_for(pipeline_id: str) -> LocalRunExecutor:
        return LocalRunExecutor(
            pipeline_id,
            root=root,
            registry=registry,
            run_store=run_store,
            publication_store=publication_store,
            job_payloads=job_payloads,
        )

    # The worker handler needs the immutable payload for document_id while
    # still receiving the validated paths from WorkerComposition.
    application = compose_application(Workspace(root / "documents", root / "templates"))
    composition = compose_worker(
        application,
        executor_for,
        root,
        queue,
        SqliteLeaseStore(state_path),
        run_store=run_store,
        passport_store=passport_store,
        finalizer=lambda result: persist_worker_evidence(
            passport_store,
            artifact_store,
            findings_store,
            result,
            workspace_root=root,
        ),
    )
    original_handle = composition.handle

    def handle(job, scratch=None):
        job_payloads[str(job.payload.get("run_id", job.id))] = dict(job.payload)
        return original_handle(job, scratch)

    composition.handle = handle  # type: ignore[method-assign]
    return WorkerRunner(composition.create_service(), poll_interval=0.2)


def persist_worker_evidence(
    passport_store: Any,
    artifact_store: Any,
    findings_store: Any,
    result: Any,
    *,
    workspace_root: Path | None = None,
) -> None:
    """Persist the real pipeline result as the run's durable evidence passport."""
    value = result.value if isinstance(result.value, dict) else {"value": result.value}
    report = value.get("report", {}) if isinstance(value, dict) else {}
    execution = report.get("execution", {}) if isinstance(report, dict) else {}
    passport_entries: list[dict[str, Any]] = [
        {
            "stage": "worker",
            "status": result.state,
            "attempt": result.attempt,
            "retry_of": result.retry_of,
            "worker_id": result.worker_id,
        },
        {"stage": "pipeline", "result": value},
    ]
    for stage in execution.get("results", ()) if isinstance(execution, dict) else ():
        if isinstance(stage, Mapping):
            # Preserve the complete stage receipt in the immutable passport so
            # Review Studio and downstream consumers can explain what ran.
            receipt = dict(stage)
            passport_entries.append(
                {"stage": "pipeline_stage", "name": receipt.get("stage", "unknown"), "receipt": receipt}
            )
    passport_store.put(Passport(result.run_id, entries=tuple(passport_entries)))
    document_id = value.get("document_id") if isinstance(value, dict) else None
    document_root = None
    if isinstance(document_id, str) and document_id and workspace_root is not None:
        document_root = workspace_root / "documents" / document_id
    for stage in execution.get("results", []) if isinstance(execution, dict) else []:
        if not isinstance(stage, dict):
            continue
        for index, produced in enumerate(stage.get("artifacts", ())):
            record = dict(produced) if isinstance(produced, Mapping) else {"value": produced}
            raw_path = record.get("path")
            candidate = Path(str(raw_path)) if raw_path else None
            if candidate is not None and not candidate.is_absolute() and workspace_root is not None:
                # Pipeline stage receipts are relative to the document's
                # durable run directory, while externally published outputs
                # may be relative to the workspace. Resolve the document
                # boundary first, then retain the workspace fallback.
                document_candidate = document_root / candidate if document_root is not None else None
                candidate = (
                    document_candidate
                    if document_candidate is not None and document_candidate.is_file()
                    else workspace_root / candidate
                )
            if candidate is not None and candidate.is_file():
                materialized = True
                digest = sha256_file(candidate)
                record["size_bytes"] = candidate.stat().st_size
            else:
                materialized = False
                encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                digest = sha256_bytes(encoded)
            artifact_store.put(
                Artifact(
                    id=f"{result.run_id}-{stage.get('stage', 'stage')}-{index}",
                    run_id=result.run_id,
                    kind=str(stage.get("stage", "artifact")),
                    digest=digest,
                    media_type=str(record.get("media_type", "")),
                    metadata={"value": record, "source": "pipeline", "materialized": materialized},
                )
            )
        for severity, messages in (("error", stage.get("errors", ())), ("warning", stage.get("warnings", ()))):
            for index, message in enumerate(messages):
                findings_store.put(
                    {
                        "id": f"{result.run_id}-{stage.get('stage', 'stage')}-{severity}-{index}",
                        "run_id": result.run_id,
                        "title": f"{stage.get('stage', 'stage')} {severity}",
                        "severity": "high" if severity == "error" else "medium",
                        "status": "failed" if severity == "error" else "warnings",
                        "location": str(stage.get("stage", "pipeline")),
                        "summary": str(message),
                    }
                )
