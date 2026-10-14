"""Durable-run plumbing behind `document run`: queue, detached worker, wait."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer

from docs.composition import RuntimeStores, resolve_runtime_root, resolve_workspace_registry
from docs.domain.pipeline_policy import PipelineMode
from docs.domain.runtime_records import Run

_FINISHED_STATUSES = {"succeeded", "completed", "failed", "cancelled", "expired"}


@dataclass(frozen=True)
class QueuedRun:
    run_id: str
    workspace_root: Path
    stores: RuntimeStores


def durable_evidence_stores(deps) -> RuntimeStores:
    return RuntimeStores(resolve_runtime_root(deps.workspace.documents_dir.parent))


def queue_run(deps, document: str, output_format: str, policy: PipelineMode) -> QueuedRun:
    """Persist a Run and enqueue its job in the active workspace's runtime store."""
    resolved = deps.resolve_context(document)
    active = resolve_workspace_registry(deps.workspace.documents_dir.parent.resolve()).active()
    if active is None:
        raise typer.BadParameter("No workspace is selected; run docs workspace use <id> first")
    workspace_root = Path(str(active["root"])).resolve()
    stores = RuntimeStores(workspace_root)
    run_id = str(uuid.uuid4())
    payload = {
        "run_id": run_id,
        "document_id": resolved.doc_id,
        "workspace_id": active["id"],
        "pipeline_id": "document",
        "format": output_format,
        "policy": policy.value,
    }
    stores.runs.put(Run(run_id, payload=payload, created_at=datetime.now(UTC).isoformat()))
    stores.queue.enqueue(run_id, payload)
    return QueuedRun(run_id, workspace_root, stores)


def spawn_detached_worker(workspace_root: Path) -> None:
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
        [
            sys.executable,
            "-m",
            "docs.local_worker",
            "--workspace-root",
            os.fspath(workspace_root),
        ],
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
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        start_new_session=True,
    )
    if hasattr(worker_output, "close"):
        worker_output.close()


def wait_for_run(queued: QueuedRun) -> None:
    store = queued.stores.runs
    while True:
        item = store.get(queued.run_id)
        if item is None:
            raise typer.BadParameter(f"Run disappeared: {queued.run_id}")
        if item.status in _FINISHED_STATUSES:
            return
        time.sleep(0.25)


def run_status(queued: QueuedRun, default: str) -> str:
    current = queued.stores.runs.get(queued.run_id)
    return current.status if current is not None else default


def run_inline(queued: QueuedRun) -> str:
    """Execute the queued job in this process through the worker composition."""
    # Import lazily to avoid making the CLI composition root depend on the
    # sidecar at import time; the worker composition remains the single
    # implementation of execution and evidence finalization.
    from docs.sidecar.worker import build_worker

    stores = queued.stores
    worker = build_worker(
        queued.workspace_root,
        stores.queue,
        stores.leases,
        stores.runs,
        stores.passports,
        stores.artifacts,
        stores.findings,
        stores.publications,
    )
    worker_result = worker.run_once()
    if worker_result is None:
        raise typer.BadParameter(f"Unable to claim synchronous run: {queued.run_id}")
    return run_status(queued, worker_result.state)
