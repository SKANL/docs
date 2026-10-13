"""HTTP handlers for run evidence: passports, findings, artifacts and previews."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict, filter_items, page_response, store_get, store_items

if TYPE_CHECKING:
    from .application import ApiApplication

import ast
import mimetypes
from collections.abc import Mapping
from pathlib import Path

from docs.application.workspaces import WorkspaceRegistryError


class EvidenceRoutes:
    """Evidence endpoints over the host application."""

    def __init__(self, host: ApiApplication) -> None:
        self._host = host

    def passport(self, run_id: str, request: Request) -> Response:
        self._host.owned_run(run_id, request)
        item = self._host.passport_store.get(run_id)
        if item is None:
            raise APIError("not_found", "Passport not found", 404)
        return Response.json(item.to_dict())

    def run_findings(self, run_id: str, request: Request) -> Response:
        self._host.owned_run(run_id, request)
        items = store_items(self._host.findings_store, "list_for_run", run_id)
        if not items:
            items = [finding for finding in (store_items(self._host.findings_store, "list") or self._host.findings) if as_dict(finding).get("run_id") == run_id]
        return page_response(items, request, "findings")

    def preview(self, run_id: str, name: str, request: Request) -> Response:
        run = self._host.owned_run(run_id, request)
        artifact = self._host.artifact_store.get(name) if hasattr(self._host.artifact_store, "get") else None
        if artifact is None or as_dict(artifact).get("run_id") != run_id:
            raise APIError("not_found", "Preview not found", 404)
        blob_key = as_dict(artifact).get("metadata", {}).get("blob_key", name)
        blob = self._host.blob_store.get(blob_key) if self._host.blob_store is not None and hasattr(self._host.blob_store, "get") else None
        if blob is not None:
            _, content = blob
            return Response(200, content, {"content-type": as_dict(artifact).get("media_type") or "application/octet-stream"})
        # Pipeline evidence may point at a real published artifact path while
        # the optional BlobStore is not configured. Serve it only after
        # resolving the run's workspace and enforcing containment; never trust
        # an arbitrary path from artifact metadata.
        payload = run.payload if isinstance(run.payload, Mapping) else {}
        workspace_id = payload.get("workspace_id")
        if self._host.workspace_registry is not None and isinstance(workspace_id, str):
            try:
                workspace_root = Path(str(self._host.resolve_workspace(workspace_id)["root"])).resolve()
                metadata = as_dict(artifact).get("metadata", {})
                raw_value = metadata.get("value") if isinstance(metadata, Mapping) else None
                record = ast.literal_eval(raw_value) if isinstance(raw_value, str) else raw_value
                candidate = Path(str(record.get("path"))) if isinstance(record, Mapping) and record.get("path") else None
                if candidate is not None and candidate.is_file():
                    resolved = candidate.resolve()
                    resolved.relative_to(workspace_root)
                    media_type = as_dict(artifact).get("media_type") or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                    return Response(200, resolved.read_bytes(), {"content-type": media_type})
            except (ValueError, OSError, SyntaxError, WorkspaceRegistryError):
                pass
        return Response.json(as_dict(artifact))

    def findings(self, request: Request) -> Response:
        items = self._host.findings_store.list() if self._host.findings_store is not None else list(self._host.findings)
        workspace_id = self._host.workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if (run := self._host.run_store.get(str(as_dict(item).get("run_id", "")))) is not None
                and as_dict(run).get("payload", {}).get("workspace_id") == workspace_id
            ]
        if request.principal is not None:
            items = [item for item in items if self._finding_is_owned(item, request.principal)]
        return page_response(filter_items(items, request.query), request, "findings")

    def _finding_is_owned(self, finding: Any, principal: Any) -> bool:
        data = as_dict(finding)
        if not isinstance(data, Mapping):
            return False

        ownership_references = 0
        run_id = data.get("run_id")
        if run_id is not None:
            ownership_references += 1
            run = self._host.run_store.get(str(run_id))
            if run is None or not self._host.is_owned(run, principal):
                return False

        document_id = data.get("document_id")
        if document_id is not None:
            ownership_references += 1
            document = (
                self._host.document_store.get(str(document_id))
                if self._host.document_store is not None and hasattr(self._host.document_store, "get")
                else None
            )
            if document is None:
                documents = (
                    self._host.document_store.list()
                    if self._host.document_store is not None and hasattr(self._host.document_store, "list")
                    else self._host.documents
                )
                document = next(
                    (item for item in documents if str(as_dict(item).get("id")) == str(document_id)),
                    None,
                )
            if document is None or not self._host.is_owned(document, principal):
                return False

        return ownership_references > 0

    def run_artifacts(self, run_id: str, request: Request) -> Response:
        self._host.owned_run(run_id, request)
        return page_response(self._host.artifact_store.list_for_run(run_id), request, "artifacts")

    def artifacts(self, request: Request) -> Response:
        items = store_items(self._host.artifact_store, "list")
        workspace_id = self._host.workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if (run := self._host.run_store.get(str(as_dict(item).get("run_id", "")))) is not None
                and as_dict(run).get("payload", {}).get("workspace_id") == workspace_id
            ]
        return page_response(filter_items(items, request.query), request, "artifacts")

    def artifact(self, artifact_id: str, request: Request) -> Response:
        workspace_id = self._host.workspace_filter(request)
        artifact = store_get(self._host.artifact_store, artifact_id, "id")
        if artifact is None:
            raise APIError("not_found", "Artifact not found", 404)
        run_id = as_dict(artifact).get("run_id")
        if run_id:
            self._host.owned_run(str(run_id), request)
        elif workspace_id and as_dict(artifact).get("workspace_id") != workspace_id:
            raise APIError("not_found", "Artifact not found", 404)
        return Response.json(as_dict(artifact))

    def artifact_previews(self, artifact_id: str, request: Request) -> Response:
        self.artifact(artifact_id, request)
        items = [
            item for item in store_items(self._host.artifact_store, "list")
            if str(as_dict(item).get("parent_artifact_id", "")) == artifact_id
            or str(as_dict(item).get("artifact_id", "")) == artifact_id
        ]
        return page_response(items, request, "previews")
