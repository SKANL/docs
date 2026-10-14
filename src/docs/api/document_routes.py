"""HTTP handlers for documents: lifecycle, import, status, sections, revisions, context and classification."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict, filter_items, page_response, store_items

if TYPE_CHECKING:
    from .application import ApiApplication

import json
import logging
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from docs.application.documents import DocumentService
from docs.application.imports import ImportError
from docs.application.workspaces import WorkspaceRegistryError
from docs.domain.ports.document_repository import DocumentExistsError, DocumentNotFoundError
from docs.domain.sections import infer_section_id_from_path

from .authoring_routes import AuthoringRoutes
from .document_dto import (
    DocumentCreateRequest,
    DocumentCurrentResponse,
    DocumentDeleteResponse,
    DocumentRenameRequest,
    DocumentSummaryDTO,
)
from .pipeline_routes import output_format
from .section_routes import SectionRoutes

_LOG = logging.getLogger("docs.api.application")



class DocumentRoutes:
    """Document endpoints over the host application."""

    def __init__(self, host: ApiApplication, sections: SectionRoutes, authoring: AuthoringRoutes) -> None:
        self._host = host
        self._sections = sections
        self._authoring = authoring

    def create(self, request: Request) -> Response:
        try:
            data = DocumentCreateRequest.model_validate(request.json(object_only=True))
        except ValidationError as exc:
            raise APIError("invalid_request", "Invalid document creation request", 400) from exc
        service = self._host.document_service(data.workspace_id)
        try:
            service.create(data.document_id, data.template, data.title)
        except DocumentExistsError as exc:
            raise APIError("document_exists", str(exc), 409) from exc
        except (ValueError, OSError, KeyError) as exc:
            raise APIError("invalid_document_request", str(exc), 400) from exc
        return Response.json(self._document_summary(service, data.document_id), 201)

    def import_source(self, request: Request) -> Response:
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = request.json(object_only=True)
        _LOG.info("document_import_started")
        workspace_id = data.get("workspace_id")
        try:
            workspace = self._host.resolve_workspace(str(workspace_id))
            result = self._host.import_service.import_base64(
                workspace["root"],
                str(data.get("filename", "")),
                str(data.get("content_base64", "")),
                document_id=data.get("document_id"),
            )
            _LOG.info("document_source_persisted")
            # Keep upload latency bounded. Document materialization is deferred
            # to prepare, where the same operation is already part of the
            # pipeline and can be observed/retried without holding the upload
            # HTTP request open.
            metadata = Path(str(result["path"])).with_suffix(".import.json")
            metadata.write_text(json.dumps({
                "template": str(data.get("template", "documento-generico")),
                "title": str(data.get("title", result["document_id"])),
            }, sort_keys=True), encoding="utf-8")
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        except ImportError as exc:
            raise APIError(str(exc), str(exc), 400) from exc
        return Response.json(result, 201)

    def import_raw(self, request: Request) -> Response:
        """Import binary source bytes without base64/JSON buffering."""
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        workspace_id = str(request.query.get("workspace_id", ""))
        try:
            workspace = self._host.resolve_workspace(workspace_id)
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        if not isinstance(request.body, (bytes, bytearray)) or not request.body:
            raise APIError("empty_source", "Source body is empty", 400)
        filename = str(request.headers.get("x-docs-filename", "source.bin"))
        result = self._host.import_service.import_bytes(
            workspace["root"], filename, bytes(request.body), document_id=request.query.get("document_id")
        )
        metadata = Path(str(result["path"])).with_suffix(".import.json")
        metadata.write_text(json.dumps({
            "template": request.query.get("template", "documento-generico"),
            "title": request.query.get("title", result["document_id"]),
        }, sort_keys=True), encoding="utf-8")
        return Response.json(result, 201)

    @staticmethod
    def _document_summary(service: DocumentService, document_id: str) -> dict[str, Any]:
        summary = next((item for item in service.list() if item.id == document_id), None)
        if summary is None:
            raise APIError("document_not_found", "Document not found", 404)
        return DocumentSummaryDTO(
            id=summary.id,
            title=summary.title,
            template=summary.template,
            created_at=summary.created_at,
            active=service.current() == summary.id,
        ).model_dump()

    def use(self, document_id: str, request: Request) -> Response:
        service = self._host.document_service(str(request.query.get("workspace_id", "")))
        try:
            service.use(document_id)
        except DocumentNotFoundError as exc:
            raise APIError("document_not_found", "Document not found", 404) from exc
        except ValueError as exc:
            raise APIError("invalid_document_id", str(exc), 400) from exc
        return Response.json(self._document_summary(service, document_id))

    def rename(self, document_id: str, request: Request) -> Response:
        try:
            data = DocumentRenameRequest.model_validate(request.json(object_only=True))
        except ValidationError as exc:
            raise APIError("invalid_request", "Invalid document rename request", 400) from exc
        service = self._host.document_service(str(request.query.get("workspace_id", "")))
        try:
            service.rename(document_id, data.new_id)
        except DocumentNotFoundError as exc:
            raise APIError("document_not_found", "Document not found", 404) from exc
        except DocumentExistsError as exc:
            raise APIError("document_exists", str(exc), 409) from exc
        except ValueError as exc:
            raise APIError("invalid_document_id", str(exc), 400) from exc
        return Response.json(self._document_summary(service, data.new_id))

    def delete(self, document_id: str, request: Request) -> Response:
        service = self._host.document_service(str(request.query.get("workspace_id", "")))
        try:
            service.delete(document_id)
        except DocumentNotFoundError as exc:
            raise APIError("document_not_found", "Document not found", 404) from exc
        except ValueError as exc:
            raise APIError("invalid_document_id", str(exc), 400) from exc
        return Response.json(DocumentDeleteResponse(
            deleted=document_id,
            current_document_id=service.current() or None,
        ).model_dump())

    def action(self, document_id: str, action: str, request: Request) -> Response:
        data = request.json(object_only=True) if request.body else {}
        workspace_id = str(data.get("workspace_id", ""))
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            workspace = self._host.resolve_workspace(workspace_id)
            if action in {"build", "verify", "publish"}:
                manifest = Path(str(workspace["root"])) / "documents" / document_id / "document.json"
                if not manifest.is_file():
                    raise APIError("document_not_found", "Document not found in workspace", 404)
                run_id = str(data.get("run_id") or uuid4())
                payload = {
                    **data,
                    "run_id": run_id,
                    "workspace_id": workspace_id,
                    "document_id": document_id,
                    "pipeline_id": "document" if action == "build" else "document-verify" if action == "verify" else "document-publish",
                    "policy": "release" if action == "publish" else str(data.get("policy", "release")),
                    "format": output_format(data.get("format", "docx")),
                }
                return Response.json(self._host.run_routes.enqueue(run_id, payload).to_dict(), 202)
            if self._host.document_action is None:
                raise APIError("document_action_unavailable", "Document actions are not configured", 501)
            result = self._host.document_action(workspace["root"], document_id, action, data)
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            raise APIError("document_action_failed", str(exc), 400) from exc
        return Response.json(result)

    def status(self, document_id: str, request: Request) -> Response:
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        try:
            workspace = self._host.resolve_workspace(str(workspace_id))
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        document_root = Path(str(workspace["root"])) / "documents" / document_id
        if not (document_root / "document.json").is_file():
            raise APIError("document_not_found", "Document not found in workspace", 404)
        if self._host.status_reader is None:
            raise APIError("status_not_configured", "Document status reader is not configured", 503)
        snapshot = self._host.status_reader.read(document_root)
        return Response.json({
            "document_id": document_id,
            "workspace_id": workspace["id"],
            "succeeded": snapshot.succeeded,
            "manifest": as_dict(snapshot.manifest),
            "capabilities": snapshot.capabilities,
            "execution": snapshot.execution,
            "provenance": snapshot.provenance,
            "unsupported_stages": snapshot.unsupported_stages,
            "publication_blockers": snapshot.publication_blockers,
        })

    def sections(self, document_id: str, request: Request) -> Response:
        """Read authored section bodies from the selected workspace.

        This endpoint is deliberately read-only; edits continue through the
        revision service so hashes and provenance cannot be bypassed.
        """
        self.get(document_id, request)
        workspace = self._host.request_workspace(request)
        root = Path(str(workspace["root"])).resolve() / "documents" / document_id / "sections"
        items = []
        for path in sorted(root.glob("*.md")) if root.is_dir() else []:
            section_id = infer_section_id_from_path(path)
            body = path.read_text(encoding="utf-8")
            items.append({"id": section_id, "filename": path.name, "body": body})
        return Response.json({"document_id": document_id, "workspace_id": workspace["id"], "items": items})

    def section(self, document_id: str, section_id: str, request: Request) -> Response:
        self.sections(document_id, request)
        workspace = self._host.request_workspace(request)
        safe_id = Path(section_id).name
        if safe_id != section_id or not section_id or section_id in {".", ".."}:
            raise APIError("invalid_section", "Invalid section identifier", 400)
        sections = Path(str(workspace["root"])).resolve() / "documents" / document_id / "sections"
        path = next((p for p in sorted(sections.glob("*.md")) if infer_section_id_from_path(p) == section_id), None)
        if path is None:
            raise APIError("section_not_found", "Section not found in workspace", 404)
        return Response.json({"document_id": document_id, "workspace_id": workspace["id"], "id": section_id, "filename": path.name, "body": path.read_text(encoding="utf-8")})

    def update_section(self, document_id: str, section_id: str, request: Request) -> Response:
        self.section(document_id, section_id, request)
        data = request.json(object_only=True)
        body = data.get("body")
        if not isinstance(body, str):
            raise APIError("invalid_section", "Section body must be a string", 400)
        if self._host.revision_service is None:
            raise APIError("revision_unavailable", "Document revision is not configured", 501)
        revision = {"target_id": section_id, "new_body": body, "request": str(data.get("request") or "Review Studio section edit")}
        try:
            result = self._host.revision_service(document_id, revision) if callable(self._host.revision_service) else self._host.revision_service.revise(document_id, revision)
        except (ValueError, FileNotFoundError) as exc:
            raise APIError("invalid_revision", str(exc), 400) from exc
        return Response.json(as_dict(result), 200)

    def list(self, request: Request) -> Response:
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        service = self._host.document_service(str(workspace_id))
        active_id = service.current()
        items = [
            DocumentSummaryDTO(
                id=item.id,
                title=item.title,
                template=item.template,
                created_at=item.created_at,
                active=item.id == active_id,
            ).model_dump()
            for item in service.list()
        ]
        if request.principal is not None:
            items = [item for item in items if self._host.is_owned(item, request.principal)]
        return page_response(filter_items(items, request.query), request, "documents")

    def current(self, request: Request) -> Response:
        service = self._host.document_service(str(request.query.get("workspace_id", "")))
        document_id = service.current() or None
        summary = self._document_summary(service, document_id) if document_id else None
        return Response.json(DocumentCurrentResponse(
            current_document_id=document_id,
            document=DocumentSummaryDTO.model_validate(summary) if summary else None,
        ).model_dump())

    def get(self, document_id: str, request: Request) -> Response:
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        document = None
        if self._host.workspace_registry is not None and not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        if workspace_id and self._host.workspace_registry is not None and hasattr(self._host.document_store, "list_for_workspace"):
            try:
                workspace = self._host.resolve_workspace(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            document = next(
                (item for item in self._host.document_store.list_for_workspace(workspace["root"])
                 if str(as_dict(item).get("id")) == document_id),
                None,
            )
        elif self._host.workspace_registry is not None:
            assert isinstance(workspace_id, str)
            try:
                workspace = self._host.resolve_workspace(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            manifest = Path(str(workspace["root"])) / "documents" / document_id / "document.json"
            if manifest.is_file():
                try:
                    document = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise APIError("document_invalid", "Document manifest is invalid", 422) from exc
            else:
                raise APIError("not_found", "Document not found", 404)
        elif self._host.document_store is not None and hasattr(self._host.document_store, "get"):
            document = self._host.document_store.get(document_id)
        if document is None:
            items = self._host.document_store.list() if self._host.document_store is not None and hasattr(self._host.document_store, "list") else self._host.documents
            document = next((item for item in items if str(as_dict(item).get("id")) == document_id), None)
        if document is None:
            raise APIError("not_found", "Document not found", 404)
        self._host.require_owned(document, request, "Document")
        return Response.json(as_dict(document))

    def runs(self, document_id: str, request: Request) -> Response:
        self.get(document_id, request)
        items = store_items(self._host.run_store, "list_for_document", document_id)
        if not items:
            items = [run for run in store_items(self._host.run_store, "list") if as_dict(run).get("payload", {}).get("document_id") == document_id]
        if request.principal is not None:
            items = [item for item in items if self._host.is_owned(item, request.principal)]
        return page_response(items, request, "runs")

    def revise(self, document_id: str, request: Request) -> Response:
        if self._host.workspace_services_factory is not None:
            return self._sections.revise(request, document_id)
        self.get(document_id, request)
        data = request.json(object_only=True)
        if callable(self._host.revision_service):
            try:
                result = self._host.revision_service(document_id, data)
            except (ValueError, FileNotFoundError) as exc:
                raise APIError("invalid_revision", str(exc), 400) from exc
        elif self._host.revision_service is not None and hasattr(self._host.revision_service, "revise"):
            result = self._host.revision_service.revise(document_id, data)
        else:
            # A revision is a mutating product operation.  Never acknowledge
            # it with an echoed request when the real application service is
            # absent: that creates a fake revision which cannot be audited or
            # recovered from the workspace.
            raise APIError("revision_unavailable", "Document revision is not configured", 501)
        return Response.json(as_dict(result), 201)

    def classification(self, document_id: str, request: Request) -> Response:
        if self._host.classification_service is None and self._host.workspace_services_factory is not None:
            return self._authoring.classification(request, document_id)
        if self._host.classification_service is None:
            raise APIError("classification_unavailable", "Classification is not configured", 501)
        try:
            result = self._host.classification_service(document_id, request.json(object_only=True) if request.body else None)
        except (ValueError, FileNotFoundError) as exc:
            raise APIError("invalid_classification", str(exc), 400) from exc
        return Response.json(result)

    def context(self, document_id: str, request: Request) -> Response:
        self.get(document_id, request)
        if request.method.upper() == "GET":
            if not callable(self._host.document_context_reader):
                raise APIError("context_unavailable", "Document context is unavailable", 503)
            workspace = self._host.request_workspace(request)
            try:
                value = self._host.document_context_reader(document_id, str(workspace["root"]))
            except TypeError:
                # Preserve the public one-argument application callback contract
                # used by embedders while allowing the sidecar to enforce the
                # requested workspace rather than its process-wide active one.
                value = self._host.document_context_reader(document_id)
            return Response.json(as_dict(value))
        if not callable(self._host.document_context_writer):
            raise APIError("context_unavailable", "Document context is unavailable", 503)
        data = request.json(object_only=True)
        topic = data.get("topic")
        value = data.get("value")
        field = data.get("field", "")
        if not isinstance(topic, str) or not topic.strip() or not isinstance(value, str):
            raise APIError("invalid_request", "topic and string value are required", 400)
        try:
            workspace = self._host.request_workspace(request)
            try:
                result = self._host.document_context_writer(document_id, topic, field, value, str(workspace["root"]))
            except TypeError:
                result = self._host.document_context_writer(document_id, topic, field, value)
        except (ValueError, FileNotFoundError) as exc:
            raise APIError("invalid_context", str(exc), 400) from exc
        return Response.json(as_dict(result), 200)
