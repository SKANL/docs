"""HTTP facade for the X20 document evidence ports."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from docs.application.graph_queries import GraphQueryService
from docs.domain.contracts import Run

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
    ) -> None:
        self.run_store = run_store
        self.queue = queue
        self.passport_store = passport_store
        self.artifact_store = artifact_store
        self.graph_store = graph_store
        self.document_store = document_store
        self.findings_store = findings_store
        self.revision_service = revision_service
        self.baseline_store = baseline_store
        self.plugin_store = plugin_store
        self.plugin_registry = plugin_registry
        self.plugins = plugins
        self.blob_store = blob_store
        self.documents = documents
        self.findings = findings
        self.router = router or Router()
        self._route_lock = threading.RLock()
        self._auth = auth
        self._dynamic_routes: set[tuple[str, str]] = set()
        self._cancel_lock = threading.Lock()
        self._static_routes = {
            ("GET", "/v1/graph"),
            ("GET", "/v1/documents"),
            ("GET", "/v1/findings"),
            ("GET", "/v1/openapi.json"),
            ("GET", "/v1/baselines"),
            ("GET", "/v1/plugins"),
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
        self._register_owned_route("POST", "/v1/baselines/promotions", self._promote_baseline)
        self._register_owned_route("POST", "/v1/runs", self._create_run)

    def dispatch(self, request: Request) -> Response:
        parts = request.route_path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] in (["v1", "runs"], ["v1", "documents"]):
            handler = self._dynamic_handler(request.method, request.route_path)
            if handler is not None:
                key = (request.method.upper(), request.route_path)
                self._install_dynamic_route(key, handler)
        return self.router.dispatch(request)

    def __call__(self, environ: Mapping[str, Any], start_response: Any) -> Any:
        path = str(environ.get("PATH_INFO", "/"))
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
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
            ("GET", "/v1/graph"): "graph:read",
            ("GET", "/v1/documents"): "documents:read",
            ("GET", "/v1/findings"): "findings:read",
            ("GET", "/v1/baselines"): "baselines:read",
            ("POST", "/v1/baselines/promotions"): "baselines:write",
            ("GET", "/v1/plugins"): "plugins:read",
            ("POST", "/v1/runs"): "runs:write",
        }
        if (method, path) in static_scopes:
            return static_scopes[(method, path)]
        parts = path.strip("/").split("/")
        if any(not part for part in parts):
            return None
        if parts[:2] == ["v1", "documents"] and len(parts) in {3, 4}:
            if len(parts) == 3 and method == "GET":
                return "documents:read"
            if len(parts) == 4 and parts[3] == "runs" and method == "GET":
                return "documents:read"
            if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
                return "documents:write"
        if parts[:2] == ["v1", "runs"]:
            if len(parts) == 3 and method == "GET":
                return "runs:read"
            if len(parts) == 4:
                if parts[3] == "cancel" and method == "POST":
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
            or parts[:2] not in (["v1", "runs"], ["v1", "documents"])
        ):
            return False
        if parts[:2] == ["v1", "documents"]:
            return (len(parts) == 3 and method == "GET") or (
                len(parts) == 4 and parts[3] == "runs" and method == "GET"
            ) or (len(parts) == 4 and parts[3] == "revisions" and method == "POST")
        if len(parts) == 3:
            return method == "GET"
        return (len(parts) == 4 and (
            (parts[3] == "cancel" and method == "POST")
            or (parts[3] in {"passport", "artifacts", "progress", "findings", "graph"} and method == "GET")
        )) or (len(parts) == 5 and parts[3] == "previews" and method == "GET")

    def _dynamic_handler(self, method: str, path: str) -> Any:
        parts = path.strip("/").split("/")
        if (
            len(parts) < 3
            or any(not part for part in parts)
            or parts[:2] not in (["v1", "runs"], ["v1", "documents"])
        ):
            return None
        resource_id = parts[2]
        if parts[:2] == ["v1", "documents"]:
            if len(parts) == 3 and method == "GET":
                return lambda _: self._document(resource_id)
            if len(parts) == 4 and parts[3] == "runs" and method == "GET":
                return lambda request: self._document_runs(resource_id, request)
            if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
                return lambda request: self._revision(resource_id, request)
            return None
        run_id = resource_id
        if len(parts) == 3 and method == "GET":
            return lambda _: self._run(run_id)
        if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
            return lambda _: self._cancel(run_id)
        if len(parts) == 4 and parts[3] == "passport" and method == "GET":
            return lambda _: self._passport(run_id)
        if len(parts) == 4 and parts[3] == "artifacts" and method == "GET":
            return lambda request: self._artifacts(run_id, request)
        if len(parts) == 4 and parts[3] == "progress" and method == "GET":
            return lambda _: self._progress(run_id)
        if len(parts) == 4 and parts[3] == "findings" and method == "GET":
            return lambda request: self._run_findings(run_id, request)
        if len(parts) == 4 and parts[3] == "graph" and method == "GET":
            return lambda request: self._run_graph(run_id, request)
        if len(parts) == 5 and parts[3] == "previews" and method == "GET":
            return lambda _: self._preview(run_id, parts[4])
        return None

    def _create_run(self, request: Request) -> Response:
        data = request.json(object_only=True)
        run_id = data.get("id") or str(uuid4())
        run = Run(run_id, payload=data, created_at=datetime.now(UTC).isoformat())
        self.run_store.put(run)
        self.queue.enqueue(run_id, dict(data))
        return Response.json(run.to_dict(), 201)

    def _run(self, run_id: str) -> Response:
        run = self.run_store.get(run_id)
        if run is None:
            raise APIError("not_found", "Run not found", 404)
        return Response.json(run.to_dict())

    def _cancel(self, run_id: str) -> Response:
        with self._cancel_lock:
            run = self.run_store.get(run_id)
            if run is None:
                raise APIError("not_found", "Run not found", 404)
            if run.status in {"cancelled", "completed", "failed"}:
                return Response.json(run.to_dict())
            cancel = getattr(self.queue, "cancel", None)
            if callable(cancel):
                cancel(run_id)
            cancelled = Run(run.id, "cancelled", run.payload, run.created_at)
            self.run_store.put(cancelled)
            return Response.json(cancelled.to_dict())

    def _passport(self, run_id: str) -> Response:
        if self.run_store.get(run_id) is None:
            raise APIError("not_found", "Run not found", 404)
        item = self.passport_store.get(run_id)
        if item is None:
            raise APIError("not_found", "Passport not found", 404)
        return Response.json(item.to_dict())

    def _artifacts(self, run_id: str, request: Request) -> Response:
        if self.run_store.get(run_id) is None:
            raise APIError("not_found", "Run not found", 404)
        return self._page(self.artifact_store.list_for_run(run_id), request, "artifacts")

    def _progress(self, run_id: str) -> Response:
        run = self.run_store.get(run_id)
        if run is None:
            raise APIError("not_found", "Run not found", 404)
        return Response(
            200,
            encode_sse_event("progress", run.to_dict(), event_id=run.id).encode(),
            {"content-type": "text/event-stream", "cache-control": "no-cache"},
        )

    def _graph(self, request: Request) -> Response:
        """Expose deterministic read-only graph queries without mutating the graph."""
        if not request.query:
            graph = self.graph_store.get()
            return Response.json(_dict(graph))
        query = GraphQueryService(self.graph_store)
        params = request.query
        mode = params.get("mode")
        query_name = params.get("query")
        if query_name is not None and mode is not None:
            raise APIError("invalid_graph_query", "query and mode cannot be used together", 400)
        selected_query = query_name if query_name is not None else mode
        identifier = params.get("id") if query_name is not None else None
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
                params["node"], relation=params.get("relation"), direction=params.get("direction", "both")
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
        if self.run_store.get(run_id) is None:
            raise APIError("not_found", "Run not found", 404)
        return self._graph(request)

    @staticmethod
    def _openapi() -> Response:
        return Response(200, canonical_json(build_openapi_document()).encode(), {"content-type": "application/json"})

    def _documents(self, request: Request) -> Response:
        items = self.document_store.list() if self.document_store is not None else list(self.documents)
        return self._page(self._filter(items, request.query), request, "documents")

    def _findings(self, request: Request) -> Response:
        items = self.findings_store.list() if self.findings_store is not None else list(self.findings)
        return self._page(self._filter(items, request.query), request, "findings")

    def _document(self, document_id: str) -> Response:
        document = self.document_store.get(document_id) if self.document_store is not None and hasattr(self.document_store, "get") else None
        if document is None:
            items = self.document_store.list() if self.document_store is not None and hasattr(self.document_store, "list") else self.documents
            document = next((item for item in items if str(_dict(item).get("id")) == document_id), None)
        if document is None:
            raise APIError("not_found", "Document not found", 404)
        return Response.json(_dict(document))

    def _document_runs(self, document_id: str, request: Request) -> Response:
        self._document(document_id)
        items = self._store_items(self.run_store, "list_for_document", document_id)
        if not items:
            items = [run for run in self._store_items(self.run_store, "list") if _dict(run).get("payload", {}).get("document_id") == document_id]
        return self._page(items, request, "runs")

    def _run_findings(self, run_id: str, request: Request) -> Response:
        items = self._store_items(self.findings_store, "list_for_run", run_id)
        if not items:
            items = [finding for finding in (self._store_items(self.findings_store, "list") or self.findings) if _dict(finding).get("run_id") == run_id]
        return self._page(items, request, "findings")

    def _preview(self, run_id: str, name: str) -> Response:
        if self.run_store.get(run_id) is None:
            raise APIError("not_found", "Run not found", 404)
        artifact = self.artifact_store.get(name) if hasattr(self.artifact_store, "get") else None
        if artifact is None or _dict(artifact).get("run_id") != run_id:
            raise APIError("not_found", "Preview not found", 404)
        blob_key = _dict(artifact).get("metadata", {}).get("blob_key", name)
        blob = self.blob_store.get(blob_key) if self.blob_store is not None and hasattr(self.blob_store, "get") else None
        if blob is not None:
            _, content = blob
            return Response(200, content, {"content-type": _dict(artifact).get("media_type") or "application/octet-stream"})
        return Response.json(_dict(artifact))

    def _revision(self, document_id: str, request: Request) -> Response:
        self._document(document_id)
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
