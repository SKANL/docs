"""HTTP facade for the X20 document evidence ports."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from docs.domain.contracts import Run

from .http import APIError, Request, Response, Router, paginate


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
            ("POST", "/v1/runs"),
        }
        self._validate_initial_route_collisions()
        self._register_owned_route("GET", "/v1/graph", lambda _: self._graph())
        self._register_owned_route("GET", "/v1/documents", self._documents)
        self._register_owned_route("GET", "/v1/findings", self._findings)
        self._register_owned_route("POST", "/v1/runs", self._create_run)

    def dispatch(self, request: Request) -> Response:
        parts = request.route_path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["v1", "runs"]:
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
            self._authenticate(request)
            return handler(request)

        return guarded

    def _authenticate(self, request: Request) -> None:
        with self._route_lock:
            validator = self._auth
        if validator is None:
            return
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or validator(token) is None:
            raise APIError("unauthorized", "Authentication required", 401)

    def _validate_initial_route_collisions(self) -> None:
        for method, path in self._registered_route_keys():
            if (method, path) in self._static_routes or self._is_dynamic_route(method, path):
                raise ValueError(f"Route collision: {method} {path} is already registered")

    def _registered_route_keys(self) -> set[tuple[str, str]]:
        return {(method, path) for method, path, _, _ in self.router._routes}

    @staticmethod
    def _is_dynamic_route(method: str, path: str) -> bool:
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["v1", "runs"]:
            return False
        if len(parts) == 3:
            return method == "GET"
        return len(parts) == 4 and (
            (parts[3] == "cancel" and method == "POST")
            or (parts[3] in {"passport", "artifacts"} and method == "GET")
        )

    def _dynamic_handler(self, method: str, path: str) -> Any:
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["v1", "runs"]:
            return None
        run_id = parts[2]
        if len(parts) == 3 and method == "GET":
            return lambda _: self._run(run_id)
        if len(parts) == 4 and parts[3] == "cancel" and method == "POST":
            return lambda _: self._cancel(run_id)
        if len(parts) == 4 and parts[3] == "passport" and method == "GET":
            return lambda _: self._passport(run_id)
        if len(parts) == 4 and parts[3] == "artifacts" and method == "GET":
            return lambda request: self._artifacts(run_id, request)
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

    def _graph(self) -> Response:
        return Response.json(self.graph_store.get().to_dict())

    def _documents(self, request: Request) -> Response:
        items = self.document_store.list() if self.document_store is not None else list(self.documents)
        return self._page(self._filter(items, request.query), request, "documents")

    def _findings(self, request: Request) -> Response:
        items = self.findings_store.list() if self.findings_store is not None else list(self.findings)
        return self._page(self._filter(items, request.query), request, "findings")

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
