"""HTTP handlers for runs: create, list, cancel, retry and the SSE progress stream."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict, filter_items, page_response, store_items

if TYPE_CHECKING:
    from .application import ApiApplication

import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from docs.application.workspaces import WorkspaceRegistryError
from docs.domain.runtime_records import Run

from .auth import AuthError
from .enterprise import encode_sse_event
from .pipeline_routes import output_format


class RunRoutes:
    """Run endpoints over the host application."""

    def __init__(self, host: ApiApplication) -> None:
        self._host = host

    def create(self, request: Request) -> Response:
        data = request.json(object_only=True)
        data["format"] = output_format(data.get("format", "docx"))
        if self._host.workspace_registry is not None:
            workspace_id = data.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                raise APIError(
                    "workspace_required",
                    "workspace_id is required to create a run",
                    400,
                )
            try:
                workspace = self._host.resolve_workspace(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            document_id = data.get("document_id")
            if isinstance(document_id, str) and document_id:
                manifest = Path(str(workspace["root"])) / "documents" / document_id / "document.json"
                if not manifest.is_file():
                    raise APIError("document_not_found", "Document not found in workspace", 404)
        if request.principal is not None:
            if request.principal.tenant_id is None or request.principal.organization_id is None:
                raise AuthError(
                    "missing_tenant_identity",
                    "Tenant and organization identity are required",
                    403,
                )
            document_id = data.get("document_id")
            if document_id is not None:
                self._host.document_routes.get(str(document_id), request)
            data.update(
                {
                    "owner_subject": request.principal.subject,
                    "tenant_id": request.principal.tenant_id,
                    "organization_id": request.principal.organization_id,
                }
            )
        run_id = data.get("id") or str(uuid4())
        # A direct run request uses the same build pipeline as the document
        # action endpoint.  The worker contract requires this explicit
        # identifier; omitting it leaves a queued job that can never execute.
        data.setdefault("pipeline_id", "document")
        # Workers receive the queued payload, not the Run wrapper. Carry the
        # authoritative generated id into that payload so a run created
        # without a caller-supplied id can execute end-to-end.
        data["run_id"] = run_id
        existing = self._host.run_store.get(run_id)
        if (
            existing is not None
            and request.principal is not None
            and not self._host.is_owned(existing, request.principal)
        ):
            raise APIError("run_id_conflict", "Run ID is unavailable", 409)
        run = Run(run_id, payload=data, created_at=datetime.now(UTC).isoformat())
        self._host.run_store.put(run)
        self._host.queue.enqueue(run_id, dict(data))
        return Response.json(run.to_dict(), 201)

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> Run:
        """The one place a durable run is stored and queued for the worker."""
        run = Run(run_id, payload=payload, created_at=datetime.now(UTC).isoformat())
        self._host.run_store.put(run)
        self._host.queue.enqueue(run_id, payload)
        return run

    def enqueue_pipeline(self, request: Request, payload: dict[str, Any]) -> Run:
        run_id = str(uuid4())
        payload = {**payload, "run_id": run_id}
        if request.principal is not None:
            if request.principal.tenant_id is None or request.principal.organization_id is None:
                raise AuthError("missing_tenant_identity", "Tenant and organization identity are required", 403)
            payload.update(
                owner_subject=request.principal.subject,
                tenant_id=request.principal.tenant_id,
                organization_id=request.principal.organization_id,
            )
        return self.enqueue(run_id, payload)

    def get(self, run_id: str, request: Request) -> Response:
        run = self._host.owned_run(run_id, request)
        return Response.json(run.to_dict())

    def list(self, request: Request) -> Response:
        items = store_items(self._host.run_store, "list")
        workspace_id = self._host.workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if as_dict(item).get("payload", {}).get("workspace_id") == workspace_id
            ]
        if request.principal is not None:
            items = [item for item in items if self._host.is_owned(item, request.principal)]
        # workspace_id is resolved from the nested run payload above; do not
        # reinterpret it as a top-level record field in the generic filter.
        item_filters = {key: value for key, value in request.query.items() if key not in {"workspace_id", "document_id"}}
        document_id = request.query.get("document_id")
        if document_id:
            items = [item for item in items if as_dict(item).get("payload", {}).get("document_id") == document_id]
        return page_response(filter_items(items, item_filters), request, "runs")

    def cancel(self, run_id: str, request: Request) -> Response:
        with self._host._cancel_lock:
            run = self._host.owned_run(run_id, request)
            if run.status in {"cancelled", "completed", "succeeded", "failed", "expired"}:
                return Response.json(run.to_dict())
            cancel = getattr(self._host.queue, "cancel", None)
            if callable(cancel):
                cancel(run_id)
            cancelled = Run(run.id, "cancelled", run.payload, run.created_at)
            self._host.run_store.put(cancelled)
            return Response.json(cancelled.to_dict())

    def retry(self, run_id: str, request: Request) -> Response:
        original = self._host.owned_run(run_id, request)
        if original.status not in {"failed", "cancelled", "expired"}:
            raise APIError("run_not_retryable", "Only failed, cancelled, or expired runs can be retried", 409)
        payload = dict(original.payload)
        retry_id = str(uuid4())
        payload.update({
            "run_id": retry_id,
            "retry_of": run_id,
            "attempt": int(payload.get("attempt", 1)) + 1,
        })
        retried = Run(retry_id, payload=payload, created_at=datetime.now(UTC).isoformat())
        self._host.run_store.put(retried)
        self._host.queue.enqueue(retry_id, payload)
        return Response.json(retried.to_dict(), 201)

    _TERMINAL_RUN_STATES = frozenset({"succeeded", "completed", "failed", "cancelled", "expired"})

    @staticmethod
    def _progress_frame(run: Run) -> bytes:
        payload = dict(run.payload) if isinstance(run.payload, Mapping) else {}
        progress = payload.get("progress")
        checkpoint: Mapping[Any, Any] = progress if isinstance(progress, Mapping) else {}
        event = {
            "type": str(checkpoint.get("stage", run.status)),
            "progress": checkpoint.get("percent"),
            "message": f"{checkpoint.get('stage', run.status)}: {checkpoint.get('percent', 0)}%",
            "run": run.to_dict(),
        }
        return encode_sse_event("progress", event, event_id=run.id).encode()

    def progress(self, run_id: str, request: Request) -> Response:
        # Ownership is checked here, before any frame is produced.
        run = self._host.owned_run(run_id, request)
        headers = {"content-type": "text/event-stream", "cache-control": "no-cache"}
        if str(request.query.get("once", "")).strip().lower() in {"1", "true", "yes", "on"}:
            return Response(200, self._progress_frame(run), headers)
        return Response(200, b"", headers, self._progress_stream(run))

    def _progress_stream(self, run: Run) -> Iterator[bytes]:
        """Emit a frame on each change until terminal, then a `terminal` event and close."""
        deadline = time.monotonic() + self._host.progress_max_seconds
        last_beat = time.monotonic()
        previous: tuple[str, Any] | None = None
        current: Run | None = run
        while current is not None:
            state = (current.status, dict(current.payload).get("progress") if isinstance(current.payload, Mapping) else None)
            if state != previous:
                previous = state
                last_beat = time.monotonic()
                yield self._progress_frame(current)
            if current.status in self._TERMINAL_RUN_STATES:
                yield encode_sse_event("terminal", {"run": current.to_dict()}, event_id=current.id).encode()
                return
            now = time.monotonic()
            if now >= deadline:
                return
            if now - last_beat >= self._host.progress_heartbeat_seconds:
                last_beat = now
                yield b": keepalive\n\n"
            time.sleep(self._host.progress_poll_interval)
            current = self._host.run_store.get(run.id)
