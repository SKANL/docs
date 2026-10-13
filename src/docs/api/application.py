"""HTTP facade for the runtime document evidence ports.

`ApiApplication` owns the WSGI/dispatch surface, authentication, route
registration and the host services (workspace resolution, ownership, composed
workspace services).  Each endpoint family lives in its own `*_routes` module.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from docs.application.documents import DocumentService
from docs.application.imports import SourceImportService
from docs.application.workspaces import WorkspaceRegistry, WorkspaceRegistryError
from docs.observability import ObservabilityPort, create_observability_from_env

from .auth import AuthError, bearer_auth
from .authoring_routes import AuthoringRoutes
from .delivery_routes import DeliveryRoutes
from .document_routes import DocumentRoutes
from .evidence_routes import EvidenceRoutes
from .graph_routes import GraphRoutes
from .http import APIError, Request, Response, Router
from .openapi import build_capability_catalog, build_openapi_document, canonical_json
from .operations import match_operation
from .pipeline_routes import PipelineRoutes
from .quality_routes import QualityRoutes
from .record_access import as_dict, store_items
from .registry_routes import RegistryRoutes
from .route_policy import DYNAMIC_ROOTS, is_dynamic_route, required_scope
from .run_routes import RunRoutes
from .section_routes import SectionRoutes
from .template_routes import TemplateRoutes
from .tool_routes import ToolRoutes
from .workspace_routes import WorkspaceRoutes


class ApiApplication:
    """Compose runtime ports behind the versioned local HTTP API."""

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
        managed_workspace_root: str | Path | None = None,
        import_service: SourceImportService | None = None,
        document_service_factory: Callable[[str], DocumentService] | None = None,
        document_action: Any = None,
        document_context_reader: Any = None,
        document_context_writer: Any = None,
        classification_service: Any = None,
        workspace_services_factory: Callable[[str], Any] | None = None,
        workspace_scoped_auth: bool = False,
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
        self._document_service_lock = threading.RLock()
        self._document_services: dict[str, DocumentService] = {}
        self._auth = auth
        self.observability = observability or create_observability_from_env()
        self.workspace_registry = workspace_registry
        self.managed_workspace_root = (
            Path(managed_workspace_root).expanduser().resolve()
            if managed_workspace_root is not None
            else workspace_registry.path.parent / "workspaces" if workspace_registry is not None else None
        )
        self.import_service = import_service or SourceImportService()
        self.document_service_factory = document_service_factory
        self.document_action = document_action
        self.document_context_reader = document_context_reader
        self.document_context_writer = document_context_writer
        self.classification_service = classification_service
        self.workspace_services_factory = workspace_services_factory
        self._workspace_services: dict[str, Any] = {}
        self._workspace_locks: dict[str, threading.Lock] = {}
        # SSE progress stream bounds: a stream never holds a worker thread longer
        # than `progress_max_seconds`; the client reconnects until terminal.
        self.progress_poll_interval = 0.5
        self.progress_heartbeat_seconds = 15.0
        self.progress_max_seconds = 300.0
        self.workspace_scoped_auth = workspace_scoped_auth
        self._dynamic_routes: set[tuple[str, str]] = set()
        self._cancel_lock = threading.Lock()
        self._build_route_groups()
        static_routes = self._static_route_table()
        self._static_routes = {(method, path) for method, path, _ in static_routes}
        self._validate_initial_route_collisions()
        for method, path, handler in static_routes:
            self._register_owned_route(method, path, handler)

    def _build_route_groups(self) -> None:
        """Instantiate every endpoint family over the shared host services."""
        root, services = self._authoring_workspace_root, self._workspace_services_for
        self._authoring = AuthoringRoutes(import_service=self.import_service, workspace_root=root, services_for=services)
        self._sections = SectionRoutes(workspace_root=root, services_for=services)
        self.workspace_routes = WorkspaceRoutes(self)
        self.document_routes = DocumentRoutes(self, sections=self._sections, authoring=self._authoring)
        self.run_routes = RunRoutes(self)
        self.graph_routes = GraphRoutes(self)
        self.evidence_routes = EvidenceRoutes(self)
        self.registry_routes = RegistryRoutes(self)
        self._pipeline = PipelineRoutes(enqueue=self.run_routes.enqueue_pipeline, workspace_root=root, services_for=services)
        self._quality = QualityRoutes(host=self, workspace_root=root, services_for=services)
        self._delivery = DeliveryRoutes(
            owned_run=self._quality._owned_run, publications=lambda: self.publication_store, workspace_root=root, services_for=services
        )
        self._templates_routes = TemplateRoutes(workspace_root=root, services_for=services)
        self._tools = ToolRoutes(quality=self._quality, import_service=self.import_service, workspace_root=root, services_for=services)
        self._operation_routes: dict[str, Any] = {
            "authoring": self._authoring, "sections": self._sections, "pipeline": self._pipeline,
            "quality": self._quality, "delivery": self._delivery, "templates": self._templates_routes,
            "tools": self._tools,
        }

    def _static_route_table(self) -> list[tuple[str, str, Any]]:
        """Every fixed (non-parameterised) route; the single source of the static set."""
        return [
            ("GET", "/v2/capabilities", lambda _: Response.json(build_capability_catalog())),
            ("GET", "/v2/graph", self.graph_routes.graph),
            ("GET", "/v2/documents", self.document_routes.list),
            ("GET", "/v2/current-document", self.document_routes.current),
            ("GET", "/v2/findings", self.evidence_routes.findings),
            ("GET", "/v2/openapi.json", lambda _: self._openapi()),
            ("GET", "/v2/baselines", self.registry_routes.baselines),
            ("GET", "/v2/plugins", self.registry_routes.plugins),
            ("GET", "/v2/runs", self.run_routes.list),
            ("GET", "/v2/artifacts", self.evidence_routes.artifacts),
            ("GET", "/v2/templates", self.registry_routes.templates),
            ("GET", "/v2/revisions", self.registry_routes.revisions),
            ("GET", "/v2/publications", self.registry_routes.publications),
            ("GET", "/v2/workspaces", self.workspace_routes.list),
            ("POST", "/v2/workspaces", self.workspace_routes.create),
            ("POST", "/v2/documents/import", self.document_routes.import_source),
            ("POST", "/v2/documents/import/raw", self.document_routes.import_raw),
            ("POST", "/v2/documents", self.document_routes.create),
            ("POST", "/v2/templates", self._templates_routes.create_template),
            ("POST", "/v2/runs", self.run_routes.create),
            ("GET", "/v2/diagnostics", self._tools.diagnostics),
            ("GET", "/v2/template-catalog", self._tools.template_catalog),
            ("POST", "/v2/translations", self._tools.translate),
            ("GET", "/v2/translations/output", self._tools.translation_output),
        ]

    def dispatch(self, request: Request) -> Response:
        with self.observability.span("docs.api.request", {"method": request.method.upper()}):
            parts = request.route_path.strip("/").split("/")
            if (
                len(parts) >= 3
                and parts[:2] in DYNAMIC_ROOTS
                and request.route_path not in {"/v2/documents/import", "/v2/documents/import/raw"}
            ):
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
            scope = required_scope(request.method, request.route_path)
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

    def _validate_initial_route_collisions(self) -> None:
        for method, path in self._registered_route_keys():
            if (method, path) in self._static_routes or is_dynamic_route(method, path):
                raise ValueError(f"Route collision: {method} {path} is already registered")

    def _registered_route_keys(self) -> set[tuple[str, str]]:
        return {(method, path) for method, path, _, _ in self.router._routes}

    def _dynamic_handler(self, method: str, path: str) -> Any:
        parts = path.strip("/").split("/")
        if (
            len(parts) < 3
            or any(not part for part in parts)
            or parts[:2] not in DYNAMIC_ROOTS
        ):
            return None
        resource_id = parts[2]
        matched = match_operation(method, path)
        if matched is not None:
            operation, params = matched
            handler = getattr(self._operation_routes[operation.routes], operation.handler)
            return lambda request: handler(request, **params)
        if parts[:2] == ["v2", "documents"]:
            return self._document_handler(method, parts)
        if parts[:2] == ["v2", "workspaces"]:
            return self._workspace_handler(method, parts)
        if parts[:2] == ["v2", "plugins"]:
            if len(parts) == 3 and method == "GET":
                return lambda request: self.registry_routes.plugin(resource_id, request)
            return None
        if parts[:2] == ["v2", "artifacts"]:
            if len(parts) == 3 and method == "GET":
                return lambda request: self.evidence_routes.artifact(resource_id, request)
            if len(parts) == 4 and parts[3] == "previews" and method == "GET":
                return lambda request: self.evidence_routes.artifact_previews(resource_id, request)
            return None
        if parts[:2] == ["v2", "revisions"] and len(parts) == 3 and method == "GET":
            return lambda request: self.registry_routes.revision_detail(resource_id, request)
        if parts[:2] == ["v2", "baselines"] and len(parts) == 3 and method == "GET":
            return lambda request: self.registry_routes.baseline(resource_id, request)
        return self._run_handler(method, parts)

    def _document_handler(self, method: str, parts: list[str]) -> Any:
        documents = self.document_routes
        document_id = parts[2]
        if len(parts) == 3 and method == "GET":
            return lambda request: documents.get(document_id, request)
        if len(parts) == 3 and method == "PATCH":
            return lambda request: documents.rename(document_id, request)
        if len(parts) == 3 and method == "DELETE":
            return lambda request: documents.delete(document_id, request)
        if len(parts) == 4 and parts[3] == "use" and method == "POST":
            return lambda request: documents.use(document_id, request)
        if len(parts) == 4 and parts[3] == "runs" and method == "GET":
            return lambda request: documents.runs(document_id, request)
        if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
            return lambda request: documents.revise(document_id, request)
        if len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST":
            return lambda request: documents.action(document_id, parts[3], request)
        if len(parts) == 4 and parts[3] == "status" and method == "GET":
            return lambda request: documents.status(document_id, request)
        if len(parts) == 4 and parts[3] == "sections" and method == "GET":
            return lambda request: documents.sections(document_id, request)
        if len(parts) == 5 and parts[3] == "sections" and method == "GET":
            return lambda request: documents.section(document_id, parts[4], request)
        if len(parts) == 5 and parts[3] == "sections" and method == "PUT":
            return lambda request: documents.update_section(document_id, parts[4], request)
        if len(parts) == 4 and parts[3] == "context" and method in {"GET", "POST"}:
            return lambda request: documents.context(document_id, request)
        if len(parts) == 4 and parts[3] == "classification" and method in {"GET", "POST"}:
            return lambda request: documents.classification(document_id, request)
        return None

    def _workspace_handler(self, method: str, parts: list[str]) -> Any:
        workspaces = self.workspace_routes
        workspace_id = parts[2]
        if len(parts) == 3 and method == "GET":
            return lambda request: workspaces.get(workspace_id, request)
        if len(parts) == 3 and method == "PATCH":
            return lambda request: workspaces.rename(workspace_id, request)
        if len(parts) == 3 and method == "DELETE":
            return lambda request: workspaces.delete(workspace_id, request)
        if len(parts) == 4 and parts[3] == "use" and method == "POST":
            return lambda request: workspaces.use(workspace_id, request)
        if len(parts) == 4 and parts[3] == "status" and method == "GET":
            return lambda request: workspaces.status(workspace_id, request)
        if len(parts) == 4 and parts[3] == "migrate" and method == "POST":
            return lambda request: workspaces.migrate(workspace_id, request)
        return None

    def _run_handler(self, method: str, parts: list[str]) -> Any:
        runs, evidence = self.run_routes, self.evidence_routes
        run_id = parts[2]
        if len(parts) == 3 and parts[2] != "runs" and method == "GET":
            return lambda request: runs.get(run_id, request)
        if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
            return lambda request: runs.cancel(run_id, request)
        if len(parts) == 4 and parts[3] == "retry" and method == "POST":
            return lambda request: runs.retry(run_id, request)
        if len(parts) == 4 and parts[3] == "passport" and method == "GET":
            return lambda request: evidence.passport(run_id, request)
        if len(parts) == 4 and parts[3] == "artifacts" and method == "GET":
            return lambda request: evidence.run_artifacts(run_id, request)
        if len(parts) == 4 and parts[3] == "progress" and method == "GET":
            return lambda request: runs.progress(run_id, request)
        if len(parts) == 4 and parts[3] == "findings" and method == "GET":
            return lambda request: evidence.run_findings(run_id, request)
        if len(parts) == 4 and parts[3] == "graph" and method == "GET":
            return lambda request: self.graph_routes.run_graph(run_id, request)
        if len(parts) == 5 and parts[3] == "previews" and method == "GET":
            return lambda request: evidence.preview(run_id, parts[4], request)
        return None

    @staticmethod
    def _openapi() -> Response:
        return Response(200, canonical_json(build_openapi_document()).encode(), {"content-type": "application/json"})

    # -- host services shared by the route groups -----------------------------
    def resolve_workspace(self, workspace_id: str) -> Mapping[str, Any]:
        """Resolve and validate a workspace before any workspace-owned I/O."""
        if self.workspace_registry is None:
            raise APIError(
                "workspace_not_configured",
                "Workspace registry is not configured",
                503,
            )
        try:
            return self.workspace_registry.resolve(workspace_id)
        except WorkspaceRegistryError as exc:
            if exc.code == "workspace_not_found":
                raise APIError(exc.code, "Workspace not found", 404) from exc
            raise APIError(exc.code, "Workspace format is invalid", 409) from exc

    def request_workspace(self, request: Request) -> Mapping[str, Any]:
        if self.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        return self.resolve_workspace(str(workspace_id))

    def workspace_filter(self, request: Request) -> str | None:
        """Return explicit workspace scope for collection endpoints."""
        requested = request.query.get("workspace_id") if hasattr(request, "query") else None
        if self.workspace_registry is not None and not requested:
            raise APIError("workspace_required", "workspace_id is required", 400)
        if requested and self.workspace_registry is not None:
            try:
                self.resolve_workspace(requested)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            return requested
        return requested

    def workspace_items(self, store: Any, request: Request) -> list[Any]:
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if self.workspace_registry is not None and not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        if workspace_id and self.workspace_registry is not None:
            try:
                self.resolve_workspace(workspace_id)
            except WorkspaceRegistryError as exc:
                raise APIError(str(exc), "Workspace not found", 404) from exc
            list_for_workspace = getattr(store, "list_for_workspace", None)
            if callable(list_for_workspace):
                return store_items(store, "list_for_workspace", workspace_id)
            return [item for item in store_items(store, "list") if as_dict(item).get("workspace_id") == workspace_id]
        return store_items(store, "list")

    def document_service(self, workspace_id: str) -> DocumentService:
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        workspace = self.resolve_workspace(workspace_id)
        if self.document_service_factory is None:
            raise APIError("document_lifecycle_unavailable", "Document lifecycle service is not configured", 501)
        workspace_root = str(Path(str(workspace["root"])).expanduser().resolve())
        with self._document_service_lock:
            cached = self._document_services.get(workspace_root)
            if cached is not None:
                return cached
            try:
                service = self.document_service_factory(workspace_root)
            except (OSError, ValueError, KeyError) as exc:
                raise APIError("document_lifecycle_unavailable", str(exc), 503) from exc
            self._document_services[workspace_root] = service
            return service

    def _authoring_workspace_root(self, request: Request, body_workspace_id: str | None) -> str:
        workspace_id = request.query.get("workspace_id") or body_workspace_id
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        workspace = self.resolve_workspace(str(workspace_id))
        return str(Path(str(workspace["root"])).expanduser().resolve())

    def _workspace_services_for(self, workspace_root: str) -> Any:
        """Composed application services for one workspace, memoized per root."""
        if self.workspace_services_factory is None:
            raise APIError("authoring_unavailable", "Authoring services are not configured", 501)
        with self._document_service_lock:  # guards only the dicts, never the slow factory
            cached = self._workspace_services.get(workspace_root)
            if cached is not None:
                return cached
            lock = self._workspace_locks.setdefault(workspace_root, threading.Lock())
        with lock:  # per-root: one composition per root, other roots proceed
            with self._document_service_lock:
                cached = self._workspace_services.get(workspace_root)
            if cached is not None:
                return cached
            try:
                services = self.workspace_services_factory(workspace_root)
            except Exception as exc:
                raise APIError("authoring_unavailable", str(exc), 503) from exc
            with self._document_service_lock:
                self._workspace_services[workspace_root] = services
            return services

    def owned_run(self, run_id: str, request: Request) -> Any:
        workspace_id = self.workspace_filter(request)
        run = self.run_store.get(run_id)
        if run is None:
            raise APIError("not_found", "Run not found", 404)
        if workspace_id and as_dict(run).get("payload", {}).get("workspace_id") != workspace_id:
            raise APIError("not_found", "Run not found", 404)
        self.require_owned(run, request, "Run")
        return run

    def require_owned(self, resource: Any, request: Request, resource_name: str) -> None:
        principal = request.principal
        if principal is None or self.is_owned(resource, principal):
            return

        raise APIError("not_found", f"{resource_name} not found", 404)

    def is_owned(self, resource: Any, principal: Any) -> bool:
        data = as_dict(resource)
        ownership = data.get("payload", data) if isinstance(data, Mapping) else {}
        if self.workspace_scoped_auth and isinstance(ownership, Mapping) and (
            "tenant_id" not in ownership and "organization_id" not in ownership
        ):
            # Self-hosted deployments have one configured workspace boundary;
            # legacy manifests created before tenant metadata existed remain
            # owned by that authenticated workspace, not anonymous globally.
            return principal.tenant_id is not None and principal.organization_id is not None
        return not (
            not isinstance(ownership, Mapping)
            or principal.tenant_id is None
            or principal.organization_id is None
            or ownership.get("tenant_id") != principal.tenant_id
            or ownership.get("organization_id") != principal.organization_id
        )
