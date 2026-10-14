"""HTTP handlers for the read-only document graph (one model: the projected `SemanticGraph`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict

if TYPE_CHECKING:
    from .application import ApiApplication

from collections.abc import Mapping
from typing import Literal, cast
from urllib.parse import urlencode, urlsplit

from docs.application.graph_queries import NAMED_QUERIES, GraphQueryService

# query name -> the parameter that carries its subject when `mode=` is used
# (the `query=` alias always uses `id`).
_BY_ID = {
    "findings_affected_by_revision": "revision_id",
    "artifacts_derived_from_input": "input_id",
    "source_impact": "source_id",
}
# Every named query, in contract order (the OpenAPI enum is built from this).
GRAPH_QUERIES = tuple(NAMED_QUERIES)


class GraphRoutes:
    """Graph endpoints over the host application."""

    def __init__(self, host: ApiApplication) -> None:
        self._host = host

    def graph(self, request: Request) -> Response:
        """Expose deterministic read-only graph queries without mutating the graph."""
        # Authenticated graph access is safe only when the application has a
        # workspace registry to scope the read model. Remote/self-hosted
        # deployments provide that registry; standalone apps still fail
        # closed rather than exposing a global graph to a principal.
        if request.principal is not None and self._host.workspace_registry is None:
            raise APIError("not_found", "Graph not found", 404)
        workspace_id = self._host.workspace_filter(request)
        semantic_store = self._host.semantic_graph_store
        if workspace_id and semantic_store is not None:
            semantic_store = semantic_store.for_workspace(workspace_id) if hasattr(semantic_store, "for_workspace") else None
        query = GraphQueryService(semantic_store)
        if not request.query or (set(request.query) == {"workspace_id"}):
            whole = query.graph()
            if whole.graph_unavailable or whole.value is None:
                return Response.json({"nodes": [], "edges": [], "graph_unavailable": True, "warnings": list(whole.warnings)})
            data = whole.value.to_dict()
            return Response.json({"nodes": data["nodes"], "edges": data["edges"], "no_data": not data["nodes"]})
        params = request.query
        mode = params.get("mode")
        query_name = params.get("query")
        if query_name is not None and mode is not None:
            raise APIError("invalid_graph_query", "query and mode cannot be used together", 400)
        selected_query = query_name if query_name is not None else mode
        identifier = params.get("id") if query_name is not None else None
        result: Any
        payload: dict[str, Any]
        if selected_query in NAMED_QUERIES:
            target = None
            if NAMED_QUERIES[selected_query]:
                identifier_name = "id" if query_name is not None else _BY_ID[selected_query]
                target = identifier if query_name is not None else params.get(identifier_name)
                if not target:
                    raise APIError("invalid_graph_query", f"{identifier_name} is required for {selected_query}", 400)
            return Response.json(query.answer(selected_query, target).to_payload())
        if selected_query is not None:
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
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        elif "relation" in params:
            result = query.find_edges(relation=params["relation"])
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        else:
            result = query.find_nodes(kind=params.get("kind"), label=params.get("label"))
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        if result.graph_unavailable:
            payload = {"items": [], "graph_unavailable": True, "warnings": list(result.warnings)}
        else:
            # "no data" (the source kinds are absent) must never read as "nothing wrong"
            coverage = query.coverage(selected_query).value or {}
            payload = {**payload, "no_data": coverage.get("no_data", True), "coverage": coverage.get("counts", {})}
        return Response.json(payload)

    def run_graph(self, run_id: str, request: Request) -> Response:
        run = self._host.owned_run(run_id, request)
        payload = as_dict(run).get("payload", {})
        run_workspace = payload.get("workspace_id") if isinstance(payload, Mapping) else None
        requested_workspace = request.query.get("workspace_id")
        if run_workspace and requested_workspace and requested_workspace != run_workspace:
            raise APIError("not_found", "Graph not found", 404)
        if run_workspace and not requested_workspace:
            query = dict(request.query)
            query["workspace_id"] = str(run_workspace)
            path = urlsplit(request.path).path + "?" + urlencode(query)
            request = Request(request.method, path, request.headers, request.body, request.environ, request.principal)
        return self.graph(request)
