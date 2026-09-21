"""HTTP facade for the X20 document evidence ports."""

from __future__ import annotations

import threading
import ast
import mimetypes
from importlib.resources import files
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from docs.application.graph_queries import GraphQueryService
from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from docs.application.status_reader import StatusReader
from docs.application.imports import ImportError, SourceImportService
from docs.domain.contracts import Run
from docs.observability import ObservabilityPort, create_observability_from_env

from .auth import AuthError, bearer_auth
from .enterprise import encode_sse_event
from .http import APIError, Request, Response, Router, paginate
from .openapi import build_openapi_document, canonical_json


def _dict(value: Any) -> Any:
    return value.to_dict() if hasattr(value, "to_dict") else dict(value) if isinstance(value, Mapping) else value


class X20Application:
    """Compose X20 ports behind the versioned local HTTP API."""

    def __init__(
        self,
        *,
        run_store: Any,
        queue: Any,
        passport_store: Any,
        artifact_store: Any,
        graph_store: Any,
        document_store: Any = None,
        findings_store: Any = None,
        template_store: Any = None,
        revision_store: Any = None,
        publication_store: Any = None,
        revision_service: Any = None,
        baseline_store: Any = None,
        plugin_store: Any = None,
        plugin_registry: Any = None,
        plugins: Iterable[Any] = (),
        blob_store: Any = None,
        documents: Iterable[Any] = (),
        findings: Iterable[Any] = (),
        router: Router | None = None,
        auth: Any = None,
        observability: ObservabilityPort | None = None,
        idempotency_persistence: Any = None,
        workspace_registry: WorkspaceRegistry | None = None,
        import_service: SourceImportService | None = None,
        document_creator: Any = None,
        document_action: Any = None,
    ) -> None:
        self.run_store = run_store
        self.queue = queue
        self.passport_store = passport_store
        self.artifact_store = artifact_store
        self.graph_store = graph_store
        self.document_store = document_store
        self.findings_store = findings_store
        self.template_store = template_store
        self.revision_store = revision_store
        self.publication_store = publication_store
        self.revision_service = revision_service
        self.baseline_store = baseline_store
        self.plugin_store = plugin_store
        self.plugin_registry = plugin_registry
        self.plugins = plugins
        self.blob_store = blob_store
        self.documents = documents
        self.findings = findings
        self.router = router or Router(idempotency_persistence=idempotency_persistence)
        self._route_lock = threading.RLock()
        self._auth = auth
        self.observability = observability or create_observability_from_env()
        self.workspace_registry = workspace_registry
        self.import_service = import_service or SourceImportService()
        self.document_creator = document_creator
        self.document_action = document_action
        self._dynamic_routes: set[tuple[str, str]] = set()
        self._cancel_lock = threading.Lock()
        self._static_routes = {
            ("GET", "/v1/graph"),
            ("GET", "/v1/documents"),
            ("GET", "/v1/findings"),
            ("GET", "/v1/openapi.json"),
            ("GET", "/v1/baselines"),
            ("GET", "/v1/plugins"),
            ("GET", "/v1/runs"),
            ("GET", "/v1/artifacts"),
            ("GET", "/v1/templates"),
            ("GET", "/v1/revisions"),
            ("GET", "/v1/publications"),
            ("GET", "/v1/workspaces"),
            ("POST", "/v1/workspaces"),
            ("POST", "/v1/documents/import"),
            ("POST", "/v1/documents"),
            ("POST", "/v1/baselines/promotions"),
            ("POST", "/v1/runs"),
        }
        self._validate_initial_route_collisions()
        self._register_owned_route("GET", "/v1/graph", self._graph)
        self._register_owned_route("GET", "/v1/documents", self._documents)
        self._register_owned_route("GET", "/v1/findings", self._findings)
        self._register_owned_route("GET", "/v1/openapi.json", lambda _: self._openapi())
        self._register_owned_route("GET", "/v1/baselines", self._baselines)
        self._register_owned_route("GET", "/v1/plugins", self._plugins)
        self._register_owned_route("GET", "/v1/runs", self._runs)
        self._register_owned_route("GET", "/v1/artifacts", self._artifacts_collection)
        self._register_owned_route("GET", "/v1/templates", self._templates)
        self._register_owned_route("GET", "/v1/revisions", self._revisions)
        self._register_owned_route("GET", "/v1/publications", self._publications)
        self._register_owned_route("GET", "/v1/workspaces", self._workspaces)
        self._register_owned_route("POST", "/v1/workspaces", self._create_workspace)
        self._register_owned_route("POST", "/v1/documents/import", self._import_document)
        self._register_owned_route("POST", "/v1/documents", self._create_document)
        self._register_owned_route("POST", "/v1/baselines/promotions", self._promote_baseline)
        self._register_owned_route("POST", "/v1/runs", self._create_run)

    def dispatch(self, request: Request) -> Response:
        with self.observability.span("docs.api.request", {"method": request.method.upper()}):
            parts = request.route_path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] in (["v1", "runs"], ["v1", "documents"], ["v1", "workspaces"]):
                handler = self._dynamic_handler(request.method, request.route_path)
                if handler is not None:
                    key = (request.method.upper(), request.route_path)
                    self._install_dynamic_route(key, handler)
            response = self.router.dispatch(request)
            self.observability.increment(
                "docs.api.request.completed",
                attributes={"method": request.method.upper(), "status": str(response.status)},
            )
            return response

    def __call__(self, environ: Mapping[str, Any], start_response: Any) -> Any:
        path = str(environ.get("PATH_INFO", "/"))
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        with self.observability.span("docs.api.request", {"method": method}):
            self._register_dynamic(method, path)
            return self.router(environ, start_response)

    def _register_dynamic(self, method: str, path: str) -> None:
        handler = self._dynamic_handler(method, path)
        if handler is not None:
            key = (method, path)
            self._install_dynamic_route(key, handler)

    def _install_dynamic_route(self, key: tuple[str, str], handler: Any) -> None:
        with self._route_lock:
            if key not in self._dynamic_routes:
                self._register_owned_route(*key, handler)
                self._dynamic_routes.add(key)

    def _register_owned_route(self, method: str, path: str, handler: Any) -> None:
        normalized = (method.upper(), path)
        with self._route_lock:
            if normalized in self._registered_route_keys():
                raise ValueError(f"Route collision: {normalized[0]} {normalized[1]} is already registered")
            self.router.route(*normalized)(self._authenticated(handler))

    @property
    def auth(self) -> Any:
        """Return the current authentication validator."""
        with self._route_lock:
            return self._auth

    @auth.setter
    def auth(self, validator: Any) -> None:
        with self._route_lock:
            self._auth = validator

    def _authenticated(self, handler: Any) -> Any:
        def guarded(request: Request) -> Response:
            with self._route_lock:
                validator = self._auth
            if validator is None:
                return handler(request)
            principal = bearer_auth(request.headers, validator)
            scope = self._required_scope(request.method, request.route_path)
            if scope is not None and scope not in principal.scopes:
                raise AuthError(
                    "insufficient_scope",
                    "Required scope is missing",
                    403,
                    headers={
                        "WWW-Authenticate": (
                            f'Bearer realm="api", error="insufficient_scope", scope="{scope}"'
                        )
                    },
                )
            return handler(request.__class__(
                request.method,
                request.path,
                request.headers,
                request.body,
                request.environ,
                principal,
            ))

        return guarded

    @staticmethod
    def _required_scope(method: str, path: str) -> str | None:
        method = method.upper()
        path = urlsplit(path).path
        static_scopes = {
            ("GET", "/v1/workspaces"): "workspaces:read",
            ("POST", "/v1/workspaces"): "workspaces:write",
            ("GET", "/v1/graph"): "graph:read",
            ("GET", "/v1/documents"): "documents:read",
            ("POST", "/v1/documents"): "documents:write",
            ("POST", "/v1/documents/import"): "documents:write",
            ("GET", "/v1/findings"): "findings:read",
            ("GET", "/v1/baselines"): "baselines:read",
            ("POST", "/v1/baselines/promotions"): "baselines:write",
            ("GET", "/v1/plugins"): "plugins:read",
            ("GET", "/v1/runs"): "runs:read",
            ("GET", "/v1/artifacts"): "artifacts:read",
            ("GET", "/v1/templates"): "documents:read",
            ("GET", "/v1/revisions"): "documents:read",
            ("GET", "/v1/publications"): "documents:read",
            ("POST", "/v1/runs"): "runs:write",
        }
        if (method, path) in static_scopes:
            return static_scopes[(method, path)]
        parts = path.strip("/").split("/")
        if any(not part for part in parts):
            return None
        if parts[:2] == ["v1", "workspaces"]:
            if len(parts) == 3 and method == "GET":
                return "workspaces:read"
            if len(parts) == 3 and method == "DELETE":
                return "workspaces:write"
            if len(parts) == 4 and parts[3] == "select" and method == "POST":
                return "workspaces:write"
        if parts[:2] == ["v1", "documents"] and len(parts) in {3, 4}:
            if len(parts) == 3 and method == "GET":
                return "documents:read"
            if len(parts) == 4 and parts[3] == "runs" and method == "GET":
                return "documents:read"
            if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
                return "documents:write"
            if len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST":
                return "documents:write"
        if parts[:2] == ["v1", "runs"]:
            if len(parts) == 3 and method == "GET":
                return "runs:read"
            if len(parts) == 4:
                if parts[3] == "cancel" and method == "POST":
                    return "runs:write"
                if parts[3] == "retry" and method == "POST":
                    return "runs:write"
                if parts[3] == "progress" and method == "GET":
                    return "runs:read"
                if parts[3] == "findings" and method == "GET":
                    return "findings:read"
                if parts[3] == "graph" and method == "GET":
                    return "graph:read"
                if parts[3] == "passport" and method == "GET":
                    return "passport:read"
                if parts[3] == "artifacts" and method == "GET":
                    return "artifacts:read"
            if len(parts) == 5 and parts[3] == "previews" and method == "GET":
                return "artifacts:read"
        return None

    def _validate_initial_route_collisions(self) -> None:
        for method, path in self._registered_route_keys():
            if (method, path) in self._static_routes or self._is_dynamic_route(method, path):
                raise ValueError(f"Route collision: {method} {path} is already registered")

    def _registered_route_keys(self) -> set[tuple[str, str]]:
        return {(method, path) for method, path, _, _ in self.router._routes}

    @staticmethod
    def _is_dynamic_route(method: str, path: str) -> bool:
        parts = path.strip("/").split("/")
        if (
            len(parts) < 3
            or any(not part for part in parts)
            or parts[:2] not in (["v1", "runs"], ["v1", "documents"], ["v1", "workspaces"])
        ):
            return False
        if parts[:2] == ["v1", "documents"]:
            return (len(parts) == 3 and method == "GET") or (
                len(parts) == 4 and parts[3] == "runs" and method == "GET"
            ) or (len(parts) == 4 and parts[3] == "revisions" and method == "POST") or (
                len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST"
            ) or (len(parts) == 4 and parts[3] == "status" and method == "GET"
            )
        if len(parts) == 3 and parts[2] != "runs":
            return method == "GET"
        return (len(parts) == 4 and (
            (parts[3] == "cancel" and method == "POST")
            or (parts[3] == "retry" and method == "POST")
            or (parts[3] in {"passport", "artifacts", "progress", "findings", "graph"} and method == "GET")
        )) or (len(parts) == 5 and parts[3] == "previews" and method == "GET")

    def _dynamic_handler(self, method: str, path: str) -> Any:
        parts = path.strip("/").split("/")
        if (
            len(parts) < 3
            or any(not part for part in parts)
            or parts[:2] not in (["v1", "runs"], ["v1", "documents"], ["v1", "workspaces"])
        ):
            return None
        resource_id = parts[2]
        if parts[:2] == ["v1", "documents"]:
            if len(parts) == 3 and method == "GET":
                return lambda request: self._document(resource_id, request)
            if len(parts) == 4 and parts[3] == "runs" and method == "GET":
                return lambda request: self._document_runs(resource_id, request)
            if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
                return lambda request: self._revision(resource_id, request)
            if len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST":
                return lambda request: self._document_action(resource_id, parts[3], request)
            if len(parts) == 4 and parts[3] == "status" and method == "GET":
                return lambda request: self._document_status(resource_id, request)
            return None
        if parts[:2] == ["v1", "workspaces"]:
            workspace_id = resource_id
            if len(parts) == 3 and method == "GET":
                return lambda request: self._workspace(workspace_id, request)
            if len(parts) == 3 and method == "PATCH":
                return lambda request: self._rename_workspace(workspace_id, request)
            if len(parts) == 4 and parts[3] == "select" and method == "POST":
                return lambda request: self._select_workspace(workspace_id, request)
            if len(parts) == 3 and method == "DELETE":
                return lambda request: self._delete_workspace(workspace_id, request)
            return None
        run_id = resource_id
        if len(parts) == 3 and parts[2] != "runs" and method == "GET":
            return lambda request: self._run(run_id, request)
        if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
            return lambda request: self._cancel(run_id, request)
        if len(parts) == 4 and parts[3] == "retry" and method == "POST":
            return lambda request: self._retry(run_id, request)
        if len(parts) == 4 and parts[3] == "passport" and method == "GET":
            return lambda request: self._passport(run_id, request)
        if len(parts) == 4 and parts[3] == "artifacts" and method == "GET":
            return lambda request: self._artifacts(run_id, request)
        if len(parts) == 4 and parts[3] == "progress" and method == "GET":
            return lambda request: self._progress(run_id, request)
        if len(parts) == 4 and parts[3] == "findings" and method == "GET":
            return lambda request: self._run_findings(run_id, request)
        if len(parts) == 4 and parts[3] == "graph" and method == "GET":
            return lambda request: self._run_graph(run_id, request)
        if len(parts) == 5 and parts[3] == "previews" and method == "GET":
            return lambda request: self._preview(run_id, parts[4], request)
        return None

    def _create_run(self, request: Request) -> Response:
        data = request.json(object_only=True)
        if self.workspace_registry is not None:
            workspace_id = data.get("workspace_id")
            if not isinstance(workspace_id, str) or not workspace_id:
                raise APIError(
                    "workspace_required",
                    "workspace_id is required to create a run",
                    400,
                )
            try:
                workspace = self.workspace_registry.get(workspace_id)
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
                self._document(str(document_id), request)
            data.update(
                {
                    "owner_subject": request.principal.subject,
                    "tenant_id": request.principal.tenant_id,
                    "organization_id": request.principal.organization_id,
                }
            )
        run_id = data.get("id") or str(uuid4())
        existing = self.run_store.get(run_id)
        if (
            existing is not None
            and request.principal is not None
            and not self._is_owned(existing, request.principal)
        ):
            raise APIError("run_id_conflict", "Run ID is unavailable", 409)
        run = Run(run_id, payload=data, created_at=datetime.now(UTC).isoformat())
        self.run_store.put(run)
        self.queue.enqueue(run_id, dict(data))
        return Response.json(run.to_dict(), 201)

    def _workspaces(self, request: Request) -> Response:
        del request
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        return Response.json({"items": self.workspace_registry.list(), "active": _dict(self.workspace_registry.active())})

    def _create_workspace(self, request: Request) -> Response:
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = request.json(object_only=True)
        try:
            item = self.workspace_registry.create(str(data.get("name", "")), str(data.get("root", "")))
        except WorkspaceRegistryError as exc:
            status = 409 if str(exc) == "workspace_name_conflict" else 400
            raise APIError(str(exc), str(exc), status) from exc
        self._seed_builtin_templates(Path(str(item["root"])))
        return Response.json(item, 201)

    @staticmethod
    def _seed_builtin_templates(workspace_root: Path) -> None:
        """Make workspaces created through the API immediately importable."""
        templates = workspace_root / "templates"
        templates.mkdir(parents=True, exist_ok=True)
        if any(templates.glob("*.json")):
            return
        package = files("docs.templates.builtin")
        for entry in package.iterdir():
            if entry.name.endswith(".json"):
                (templates / entry.name).write_text(
                    entry.read_text(encoding="utf-8"), encoding="utf-8"
                )

    def _import_document(self, request: Request) -> Response:
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = request.json(object_only=True)
        workspace_id = data.get("workspace_id")
        try:
            workspace = self.workspace_registry.get(str(workspace_id))
            result = self.import_service.import_base64(
                workspace["root"],
                str(data.get("filename", "")),
                str(data.get("content_base64", "")),
                document_id=data.get("document_id"),
            )
            # Import is a product operation, not merely a file copy. When the
            # caller did not create the document first, materialize its real
            # manifest now so the next prepare/build/verify step can run.
            document_root = Path(str(workspace["root"])) / "documents" / str(result["document_id"])
            manifest = document_root / "document.json"
            if not manifest.is_file() and self.document_creator is not None:
                result["document"] = self.document_creator(
                    workspace["root"],
                    str(result["document_id"]),
                    str(data.get("template", "documento-generico")),
                    str(data.get("title", result["document_id"])),
                )
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        except ImportError as exc:
            raise APIError(str(exc), str(exc), 400) from exc
        return Response.json(result, 201)

    def _create_document(self, request: Request) -> Response:
        if self.document_creator is None:
            raise APIError("document_creation_unavailable", "Document creation is not configured", 501)
        data = request.json(object_only=True)
        workspace_id = str(data.get("workspace_id", ""))
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            workspace = self.workspace_registry.get(workspace_id)
            result = self.document_creator(
                workspace["root"],
                str(data.get("document_id", "")),
                str(data.get("template", "documento-generico")),
                str(data.get("title", "")),
            )
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        except (ValueError, OSError, KeyError) as exc:
            raise APIError("document_creation_failed", str(exc), 400) from exc
        return Response.json(result, 201)

    def _document_action(self, document_id: str, action: str, request: Request) -> Response:
        data = request.json(object_only=True) if request.body else {}
        workspace_id = str(data.get("workspace_id", ""))
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            workspace = self.workspace_registry.get(workspace_id)
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
                    "format": str(data.get("format", "docx")),
                }
                run = Run(run_id, payload=payload, created_at=datetime.now(UTC).isoformat())
                self.run_store.put(run)
                self.queue.enqueue(run_id, payload)
                return Response.json(run.to_dict(), 202)
            if self.document_action is None:
                raise APIError("document_action_unavailable", "Document actions are not configured", 501)
            result = self.document_action(workspace["root"], document_id, action, data)
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            raise APIError("document_action_failed", str(exc), 400) from exc
        return Response.json(result)

    def _document_status(self, document_id: str, request: Request) -> Response:
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        try:
            workspace = self.workspace_registry.get(str(workspace_id)) if workspace_id else self.workspace_registry.active()
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        if workspace is None:
            raise APIError("workspace_not_configured", "Select a workspace before reading document status", 503)
        document_root = Path(str(workspace["root"])) / "documents" / document_id
        if not (document_root / "document.json").is_file():
            raise APIError("document_not_found", "Document not found in workspace", 404)
        snapshot = StatusReader().read(document_root)
        return Response.json({
            "document_id": document_id,
            "workspace_id": workspace["id"],
            "succeeded": snapshot.succeeded,
            "manifest": _dict(snapshot.manifest),
            "capabilities": snapshot.capabilities,
            "execution": snapshot.execution,
            "provenance": snapshot.provenance,
            "unsupported_stages": snapshot.unsupported_stages,
            "publication_blockers": snapshot.publication_blockers,
        })

    def _workspace(self, workspace_id: str, request: Request) -> Response:
        del request
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            return Response.json(self.workspace_registry.get(workspace_id))
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc

    def _select_workspace(self, workspace_id: str, request: Request) -> Response:
        del request
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            return Response.json(self.workspace_registry.select(workspace_id))
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc

    def _rename_workspace(self, workspace_id: str, request: Request) -> Response:
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = request.json(object_only=True)
        try:
            return Response.json(self.workspace_registry.rename(workspace_id, str(data.get("name", ""))))
        except WorkspaceRegistryError as exc:
            status = 409 if str(exc) == "workspace_name_conflict" else 400
            if str(exc) == "workspace_not_found":
                status = 404
            raise APIError(str(exc), str(exc), status) from exc

    def _delete_workspace(self, workspace_id: str, request: Request) -> Response:
        del request
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            self.workspace_registry.delete(workspace_id)
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        return Response.json({"deleted": workspace_id})

    def _run(self, run_id: str, request: Request) -> Response:
        run = self._owned_run(run_id, request)
        return Response.json(run.to_dict())

    def _runs(self, request: Request) -> Response:
        items = self._store_items(self.run_store, "list")
        workspace_id = self._workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if _dict(item).get("payload", {}).get("workspace_id") in {workspace_id, None}
            ]
        if request.principal is not None:
            items = [item for item in items if self._is_owned(item, request.principal)]
        return self._page(self._filter(items, request.query), request, "runs")

    def _owned_run(self, run_id: str, request: Request) -> Run:
        run = self.run_store.get(run_id)
        if run is None:
            raise APIError("not_found", "Run not found", 404)
        self._require_owned(run, request, "Run")
        return run

    @staticmethod
    def _require_owned(resource: Any, request: Request, resource_name: str) -> None:
        principal = request.principal
        if principal is None or X20Application._is_owned(resource, principal):
            return

        raise APIError("not_found", f"{resource_name} not found", 404)

    @staticmethod
    def _is_owned(resource: Any, principal: Any) -> bool:
        data = _dict(resource)
        ownership = data.get("payload", data) if isinstance(data, Mapping) else {}
        return not (
            not isinstance(ownership, Mapping)
            or principal.tenant_id is None
            or principal.organization_id is None
            or ownership.get("tenant_id") != principal.tenant_id
            or ownership.get("organization_id") != principal.organization_id
        )

    def _cancel(self, run_id: str, request: Request) -> Response:
        with self._cancel_lock:
            run = self._owned_run(run_id, request)
            if run.status in {"cancelled", "completed", "failed"}:
                return Response.json(run.to_dict())
            cancel = getattr(self.queue, "cancel", None)
            if callable(cancel):
                cancel(run_id)
            cancelled = Run(run.id, "cancelled", run.payload, run.created_at)
            self.run_store.put(cancelled)
            return Response.json(cancelled.to_dict())

    def _retry(self, run_id: str, request: Request) -> Response:
        original = self._owned_run(run_id, request)
        if original.status not in {"failed", "cancelled", "expired"}:
            raise APIError("run_not_retryable", "Only failed, cancelled, or expired runs can be retried", 409)
        payload = dict(original.payload)
        retry_id = str(uuid4())
        payload.update({"retry_of": run_id, "attempt": int(payload.get("attempt", 1)) + 1})
        retried = Run(retry_id, payload=payload, created_at=datetime.now(UTC).isoformat())
        self.run_store.put(retried)
        self.queue.enqueue(retry_id, payload)
        return Response.json(retried.to_dict(), 201)

    def _passport(self, run_id: str, request: Request) -> Response:
        self._owned_run(run_id, request)
        item = self.passport_store.get(run_id)
        if item is None:
            raise APIError("not_found", "Passport not found", 404)
        return Response.json(item.to_dict())

    def _artifacts(self, run_id: str, request: Request) -> Response:
        self._owned_run(run_id, request)
        return self._page(self.artifact_store.list_for_run(run_id), request, "artifacts")

    def _progress(self, run_id: str, request: Request) -> Response:
        run = self._owned_run(run_id, request)
        payload = dict(run.payload) if isinstance(run.payload, Mapping) else {}
        checkpoint = payload.get("progress") if isinstance(payload.get("progress"), Mapping) else {}
        event = {
            "type": str(checkpoint.get("stage", run.status)),
            "progress": checkpoint.get("percent"),
            "message": f"{checkpoint.get('stage', run.status)}: {checkpoint.get('percent', 0)}%",
            "run": run.to_dict(),
        }
        return Response(
            200,
            encode_sse_event("progress", event, event_id=run.id).encode(),
            {"content-type": "text/event-stream", "cache-control": "no-cache"},
        )

    def _graph(self, request: Request) -> Response:
        """Expose deterministic read-only graph queries without mutating the graph."""
        if request.principal is not None:
            raise APIError("not_found", "Graph not found", 404)
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        graph_store = self.graph_store
        if workspace_id and hasattr(self.graph_store, "for_workspace"):
            if self.workspace_registry is not None:
                self.workspace_registry.get(workspace_id)
            graph_store = self.graph_store.for_workspace(workspace_id)
        if not request.query or (set(request.query) == {"workspace_id"}):
            graph = graph_store.get()
            data = _dict(graph)
            if not isinstance(data, Mapping):
                data = {}
            return Response.json({"nodes": list(data.get("nodes", [])), "edges": list(data.get("edges", []))})
        query = GraphQueryService(graph_store)
        params = request.query
        mode = params.get("mode")
        query_name = params.get("query")
        if query_name is not None and mode is not None:
            raise APIError("invalid_graph_query", "query and mode cannot be used together", 400)
        selected_query = query_name if query_name is not None else mode
        identifier = params.get("id") if query_name is not None else None
        result: Any
        payload: dict[str, Any]
        if selected_query == "claims_without_evidence":
            result = query.claims_without_evidence()
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif selected_query == "findings_affected_by_revision":
            revision_id = identifier if query_name is not None else params.get("revision_id")
            if not revision_id:
                identifier_name = "id" if query_name is not None else "revision_id"
                raise APIError(
                    "invalid_graph_query",
                    f"{identifier_name} is required for findings_affected_by_revision",
                    400,
                )
            result = query.findings_affected_by_revision(revision_id)
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif selected_query == "artifacts_derived_from_input":
            input_id = identifier if query_name is not None else params.get("input_id")
            if not input_id:
                identifier_name = "id" if query_name is not None else "input_id"
                raise APIError(
                    "invalid_graph_query",
                    f"{identifier_name} is required for artifacts_derived_from_input",
                    400,
                )
            result = query.artifacts_derived_from_input(input_id)
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif selected_query == "unused_references":
            result = query.unused_references()
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif selected_query == "unmet_requirements":
            result = query.unmet_requirements()
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif selected_query is not None:
            parameter_name = "query" if query_name is not None else "mode"
            raise APIError(
                "invalid_graph_query",
                f"Unsupported graph query {parameter_name}: {selected_query}",
                400,
            )
        elif "source" in params and "target" in params:
            result = query.shortest_path(params["source"], params["target"])
            payload = {"path": result.value}
        elif "node" in params:
            result = query.neighbors(
                params["node"],
                relation=params.get("relation"),
                direction=cast(Literal["in", "out", "both"], params.get("direction", "both")),
            )
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        elif "relation" in params:
            result = query.find_edges(relation=params["relation"])
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        else:
            result = query.find_nodes(kind=params.get("kind"), label=params.get("label"))
            payload = {"items": [_dict(item) for item in (result.value or ())]}
        if result.graph_unavailable:
            payload = {"items": [], "graph_unavailable": True, "warnings": list(result.warnings)}
        return Response.json(payload)

    def _run_graph(self, run_id: str, request: Request) -> Response:
        run = self._owned_run(run_id, request)
        payload = _dict(run).get("payload", {})
        run_workspace = payload.get("workspace_id") if isinstance(payload, Mapping) else None
        requested_workspace = request.query.get("workspace_id")
        if run_workspace and requested_workspace and requested_workspace != run_workspace:
            raise APIError("not_found", "Graph not found", 404)
        if run_workspace and not requested_workspace:
            query = dict(request.query)
            query["workspace_id"] = str(run_workspace)
            path = urlsplit(request.path).path + "?" + urlencode(query)
            request = Request(request.method, path, request.headers, request.body, request.environ, request.principal)
        return self._graph(request)

    @staticmethod
    def _openapi() -> Response:
        return Response(200, canonical_json(build_openapi_document()).encode(), {"content-type": "application/json"})

    def _documents(self, request: Request) -> Response:
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if workspace_id and self.workspace_registry is not None and hasattr(self.document_store, "list_for_workspace"):
            try:
                workspace = self.workspace_registry.get(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            items = self.document_store.list_for_workspace(workspace["root"])
        else:
            items = self.document_store.list() if self.document_store is not None else list(self.documents)
        if request.principal is not None:
            items = [item for item in items if self._is_owned(item, request.principal)]
        return self._page(self._filter(items, request.query), request, "documents")

    def _findings(self, request: Request) -> Response:
        items = self.findings_store.list() if self.findings_store is not None else list(self.findings)
        workspace_id = self._workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if (run := self.run_store.get(str(_dict(item).get("run_id", "")))) is not None
                and _dict(run).get("payload", {}).get("workspace_id") in {workspace_id, None}
            ]
        if request.principal is not None:
            items = [item for item in items if self._finding_is_owned(item, request.principal)]
        return self._page(self._filter(items, request.query), request, "findings")

    def _artifacts_collection(self, request: Request) -> Response:
        items = self._store_items(self.artifact_store, "list")
        workspace_id = self._workspace_filter(request)
        if workspace_id:
            items = [
                item for item in items
                if (run := self.run_store.get(str(_dict(item).get("run_id", "")))) is not None
                and _dict(run).get("payload", {}).get("workspace_id") in {workspace_id, None}
            ]
        return self._page(self._filter(items, request.query), request, "artifacts")

    def _workspace_filter(self, request: Request) -> str | None:
        """Scope collection endpoints to the selected workspace by default."""
        requested = request.query.get("workspace_id") if hasattr(request, "query") else None
        if requested and self.workspace_registry is not None:
            try:
                self.workspace_registry.get(requested)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            return requested
        if requested or self.workspace_registry is None:
            return requested
        active = self.workspace_registry.active()
        return str(active["id"]) if active is not None else None

    def _templates(self, request: Request) -> Response:
        return self._page(self._filter(self._store_items(self.template_store, "list"), request.query), request, "templates")

    def _revisions(self, request: Request) -> Response:
        return self._page(self._filter(self._store_items(self.revision_store, "list"), request.query), request, "revisions")

    def _publications(self, request: Request) -> Response:
        return self._page(self._filter(self._store_items(self.publication_store, "list"), request.query), request, "publications")

    def _finding_is_owned(self, finding: Any, principal: Any) -> bool:
        data = _dict(finding)
        if not isinstance(data, Mapping):
            return False

        ownership_references = 0
        run_id = data.get("run_id")
        if run_id is not None:
            ownership_references += 1
            run = self.run_store.get(str(run_id))
            if run is None or not self._is_owned(run, principal):
                return False

        document_id = data.get("document_id")
        if document_id is not None:
            ownership_references += 1
            document = (
                self.document_store.get(str(document_id))
                if self.document_store is not None and hasattr(self.document_store, "get")
                else None
            )
            if document is None:
                documents = (
                    self.document_store.list()
                    if self.document_store is not None and hasattr(self.document_store, "list")
                    else self.documents
                )
                document = next(
                    (item for item in documents if str(_dict(item).get("id")) == str(document_id)),
                    None,
                )
            if document is None or not self._is_owned(document, principal):
                return False

        return ownership_references > 0

    def _document(self, document_id: str, request: Request) -> Response:
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        document = None
        if workspace_id and self.workspace_registry is not None and hasattr(self.document_store, "list_for_workspace"):
            try:
                workspace = self.workspace_registry.get(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            document = next(
                (item for item in self.document_store.list_for_workspace(workspace["root"])
                 if str(_dict(item).get("id")) == document_id),
                None,
            )
        elif self.document_store is not None and hasattr(self.document_store, "get"):
            document = self.document_store.get(document_id)
        if document is None:
            items = self.document_store.list() if self.document_store is not None and hasattr(self.document_store, "list") else self.documents
            document = next((item for item in items if str(_dict(item).get("id")) == document_id), None)
        if document is None:
            raise APIError("not_found", "Document not found", 404)
        self._require_owned(document, request, "Document")
        return Response.json(_dict(document))

    def _document_runs(self, document_id: str, request: Request) -> Response:
        self._document(document_id, request)
        items = self._store_items(self.run_store, "list_for_document", document_id)
        if not items:
            items = [run for run in self._store_items(self.run_store, "list") if _dict(run).get("payload", {}).get("document_id") == document_id]
        if request.principal is not None:
            items = [item for item in items if self._is_owned(item, request.principal)]
        return self._page(items, request, "runs")

    def _run_findings(self, run_id: str, request: Request) -> Response:
        self._owned_run(run_id, request)
        items = self._store_items(self.findings_store, "list_for_run", run_id)
        if not items:
            items = [finding for finding in (self._store_items(self.findings_store, "list") or self.findings) if _dict(finding).get("run_id") == run_id]
        return self._page(items, request, "findings")

    def _preview(self, run_id: str, name: str, request: Request) -> Response:
        run = self._owned_run(run_id, request)
        artifact = self.artifact_store.get(name) if hasattr(self.artifact_store, "get") else None
        if artifact is None or _dict(artifact).get("run_id") != run_id:
            raise APIError("not_found", "Preview not found", 404)
        blob_key = _dict(artifact).get("metadata", {}).get("blob_key", name)
        blob = self.blob_store.get(blob_key) if self.blob_store is not None and hasattr(self.blob_store, "get") else None
        if blob is not None:
            _, content = blob
            return Response(200, content, {"content-type": _dict(artifact).get("media_type") or "application/octet-stream"})
        # Pipeline evidence may point at a real published artifact path while
        # the optional BlobStore is not configured. Serve it only after
        # resolving the run's workspace and enforcing containment; never trust
        # an arbitrary path from artifact metadata.
        payload = run.payload if isinstance(run.payload, Mapping) else {}
        workspace_id = payload.get("workspace_id")
        if self.workspace_registry is not None and isinstance(workspace_id, str):
            try:
                workspace_root = Path(str(self.workspace_registry.get(workspace_id)["root"])).resolve()
                metadata = _dict(artifact).get("metadata", {})
                raw_value = metadata.get("value") if isinstance(metadata, Mapping) else None
                record = ast.literal_eval(raw_value) if isinstance(raw_value, str) else raw_value
                candidate = Path(str(record.get("path"))) if isinstance(record, Mapping) and record.get("path") else None
                if candidate is not None and candidate.is_file():
                    resolved = candidate.resolve()
                    resolved.relative_to(workspace_root)
                    media_type = _dict(artifact).get("media_type") or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                    return Response(200, resolved.read_bytes(), {"content-type": media_type})
            except (ValueError, OSError, SyntaxError, WorkspaceRegistryError):
                pass
        return Response.json(_dict(artifact))

    def _revision(self, document_id: str, request: Request) -> Response:
        self._document(document_id, request)
        data = request.json(object_only=True)
        if callable(self.revision_service):
            result = self.revision_service(document_id, data)
        elif self.revision_service is not None and hasattr(self.revision_service, "revise"):
            result = self.revision_service.revise(document_id, data)
        else:
            result = {"document_id": document_id, **data}
        return Response.json(_dict(result), 201)

    def _baselines(self, request: Request) -> Response:
        return self._page(self._store_items(self.baseline_store, "list"), request, "baselines")

    def _plugins(self, request: Request) -> Response:
        if self.plugin_registry is not None:
            items = [
                {
                    "id": item.manifest.plugin_id,
                    "version": item.manifest.version,
                    "capabilities": sorted(item.manifest.capabilities),
                    "trust": item.trust,
                    "digest": item.digest,
                    "artifact_digest": item.artifact_digest,
                    "sbom": item.sbom,
                }
                for item in self.plugin_registry.list()
            ]
        else:
            items = self._store_items(self.plugin_store, "list") or list(self.plugins)
        return self._page(items, request, "plugins")

    def _promote_baseline(self, request: Request) -> Response:
        data = request.json(object_only=True)
        baseline_id = data.get("baseline_id") or data.get("id")
        if not baseline_id:
            raise APIError("invalid_request", "baseline_id is required", 400)
        promote = getattr(self.baseline_store, "promote", None)
        if not callable(promote):
            raise APIError("not_found", "Baseline not found", 404)
        result = promote(baseline_id, data)
        if result is None:
            raise APIError("not_found", "Baseline not found", 404)
        return Response.json(_dict(result))

    @staticmethod
    def _store_items(store: Any, method: str, *args: Any) -> list[Any]:
        callback = getattr(store, method, None) if store is not None else None
        if not callable(callback):
            return []
        result = callback(*args)
        return list(result or [])

    @staticmethod
    def _filter(items: Iterable[Any], query: Mapping[str, str]) -> list[Any]:
        filters = {k: v for k, v in query.items() if k not in {"limit", "cursor"}}
        return [item for item in items if all(str(_dict(item).get(key)) == value for key, value in filters.items())]

    @staticmethod
    def _page(items: Iterable[Any], request: Request, resource: str) -> Response:
        query = request.query
        raw_limit = query.get("limit", "20")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise APIError("invalid_pagination", "limit must be an integer") from exc
        page = paginate(
            [_dict(item) for item in items], limit=limit, cursor=query.get("cursor"), resource=resource, query=query
        )
        return Response.json(page)
