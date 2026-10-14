"""HTTP handlers for the read-only graph model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict

if TYPE_CHECKING:
    from .application import ApiApplication

from collections.abc import Mapping
from typing import Literal, cast
from urllib.parse import urlencode, urlsplit

from docs.application.graph_queries import GraphQueryService


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
        # ponytail: GraphQueryService is typed on SemanticGraphStore while the
        # host serves the runtime Graph; the shapes differ (pre-existing, hidden
        # by the old Any slot). Reconcile the two graph models before narrowing.
        graph_store: Any = self._host.graph_store
        if workspace_id and hasattr(self._host.graph_store, "for_workspace"):
            graph_store = self._host.graph_store.for_workspace(workspace_id)
        elif workspace_id:
            raise APIError("workspace_graph_unavailable", "Workspace-scoped graph is not configured", 503)
        if not request.query or (set(request.query) == {"workspace_id"}):
            graph = graph_store.get()
            data = as_dict(graph)
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
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
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
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
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
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        elif selected_query == "unused_references":
            result = query.unused_references()
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        elif selected_query == "unmet_requirements":
            result = query.unmet_requirements()
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
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
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        elif "relation" in params:
            result = query.find_edges(relation=params["relation"])
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        else:
            result = query.find_nodes(kind=params.get("kind"), label=params.get("label"))
            payload = {"items": [as_dict(item) for item in (result.value or ())]}
        if result.graph_unavailable:
            payload = {"items": [], "graph_unavailable": True, "warnings": list(result.warnings)}
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
