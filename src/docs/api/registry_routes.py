"""HTTP handlers for registry-style read models: templates, revisions, publications, baselines and plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response
from .record_access import as_dict, filter_items, page_response, store_items

if TYPE_CHECKING:
    from .application import ApiApplication

from pathlib import Path

from docs.application.workspaces import WorkspaceRegistryError


class RegistryRoutes:
    """Registry read-model endpoints over the host application."""

    def __init__(self, host: ApiApplication) -> None:
        self._host = host

    def templates(self, request: Request) -> Response:
        return page_response(filter_items(self._host.workspace_items(self._host.template_store, request), request.query), request, "templates")

    def revisions(self, request: Request) -> Response:
        return page_response(filter_items(self._host.workspace_items(self._host.revision_store, request), request.query), request, "revisions")

    def revision_detail(self, revision_id: str, request: Request) -> Response:
        revision = next((item for item in self._host.workspace_items(self._host.revision_store, request) if any(str(as_dict(item).get(key, "")) == revision_id for key in ("id", "revision_id"))), None)
        if revision is None:
            raise APIError("not_found", "Revision not found", 404)
        return Response.json(as_dict(revision))

    def publications(self, request: Request) -> Response:
        return page_response(filter_items(self._host.workspace_items(self._host.publication_store, request), request.query), request, "publications")

    def baselines(self, request: Request) -> Response:
        return page_response(self._host.workspace_items(self._host.baseline_store, request), request, "baselines")

    def baseline(self, baseline_id: str, request: Request) -> Response:
        baseline = next((item for item in self._host.workspace_items(self._host.baseline_store, request) if any(str(as_dict(item).get(key, "")) == baseline_id for key in ("id", "baseline_id"))), None)
        if baseline is None:
            raise APIError("not_found", "Baseline not found", 404)
        return Response.json(as_dict(baseline))

    def plugins(self, request: Request) -> Response:
        if self._host.plugin_registry is not None:
            registry = self._plugin_registry_for_request(request)
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
                for item in registry.list()
            ]
        else:
            items = store_items(self._host.plugin_store, "list") or list(self._host.plugins)
        return page_response(items, request, "plugins")

    def plugin(self, plugin_id: str, request: Request) -> Response:
        """Return one registered plugin using the same normalized contract as the collection."""
        if self._host.plugin_registry is not None:
            items = self._plugin_registry_for_request(request).list()
            for item in items:
                if item.manifest.plugin_id == plugin_id:
                    return Response.json(
                        {
                            "id": item.manifest.plugin_id,
                            "version": item.manifest.version,
                            "capabilities": sorted(item.manifest.capabilities),
                            "trust": item.trust,
                            "digest": item.digest,
                            "artifact_digest": item.artifact_digest,
                            "sbom": item.sbom,
                        }
                    )
        else:
            for item in store_items(self._host.plugin_store, "list") or list(self._host.plugins):
                value = as_dict(item)
                if str(value.get("id", value.get("plugin_id", ""))) == plugin_id:
                    return Response.json(value)
        raise APIError("not_found", "Plugin not found", 404)

    def _plugin_registry_for_request(self, request: Request) -> Any:
        """Build a workspace-local registry so same-id plugins cannot collide."""
        if self._host.workspace_registry is None:
            return self._host.plugin_registry
        workspace_id = request.query.get("workspace_id") if hasattr(request, "query") else None
        if not workspace_id:
            raise APIError("workspace_required", "workspace_id is required", 400)
        try:
            workspace = self._host.resolve_workspace(str(workspace_id))
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        try:
            registry = type(self._host.plugin_registry)()
            registry.discover([Path(str(workspace["root"])) / "plugins"])
            return registry
        except (TypeError, AttributeError):
            # Embedded callers may provide a custom registry implementation;
            # retain its contract instead of making plugin listing mandatory.
            return self._host.plugin_registry
