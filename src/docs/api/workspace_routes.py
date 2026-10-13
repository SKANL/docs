"""HTTP handlers for the workspace registry: list, create, rename, delete, select, status."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .http import APIError, Request, Response

if TYPE_CHECKING:
    from .application import ApiApplication

from collections.abc import Mapping
from uuid import uuid4

from pydantic import ValidationError

from docs.application.workspaces import WorkspaceRegistryError

from .workspace_dto import (
    WorkspaceCreateRequest,
    WorkspaceDeleteResponse,
    WorkspacePage,
    WorkspaceRenameRequest,
    WorkspaceResponse,
    WorkspaceStatusResponse,
)


class WorkspaceRoutes:
    """Workspace registry endpoints over the host application."""

    def __init__(self, host: ApiApplication) -> None:
        self._host = host

    def list(self, request: Request) -> Response:
        del request
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        page = WorkspacePage(
            items=[WorkspaceResponse.model_validate(item) for item in self._host.workspace_registry.list()]
        )
        return Response.json(page.model_dump(mode="json"))

    @staticmethod
    def _workspace_request(
        model: type[WorkspaceCreateRequest] | type[WorkspaceRenameRequest],
        request: Request,
    ) -> WorkspaceCreateRequest | WorkspaceRenameRequest:
        try:
            return model.model_validate(request.json(object_only=True))
        except ValidationError as exc:
            raise APIError("invalid_request", "Request body does not match workspace contract", 400) from exc

    @staticmethod
    def _workspace_response(item: Mapping[str, Any]) -> dict[str, str]:
        return WorkspaceResponse.model_validate(item).model_dump(mode="json")

    def create(self, request: Request) -> Response:
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = self._workspace_request(WorkspaceCreateRequest, request)
        if self._host.managed_workspace_root is None:
            raise APIError("workspace_root_not_configured", "Managed workspace root is not configured", 503)
        root = self._host.managed_workspace_root / uuid4().hex
        try:
            item = self._host.workspace_registry.create(data.name, root)
        except WorkspaceRegistryError as exc:
            status = 409 if str(exc) == "workspace_name_conflict" else 400
            raise APIError(str(exc), str(exc), status) from exc
        return Response.json(self._workspace_response(item), 201)

    def get(self, workspace_id: str, request: Request) -> Response:
        del request
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            return Response.json(self._workspace_response(self._host.workspace_registry.get(workspace_id)))
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc

    def rename(self, workspace_id: str, request: Request) -> Response:
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        data = self._workspace_request(WorkspaceRenameRequest, request)
        try:
            return Response.json(self._workspace_response(self._host.workspace_registry.rename(workspace_id, data.name)))
        except WorkspaceRegistryError as exc:
            status = 409 if str(exc) == "workspace_name_conflict" else 400
            if str(exc) == "workspace_not_found":
                status = 404
            raise APIError(str(exc), str(exc), status) from exc

    def delete(self, workspace_id: str, request: Request) -> Response:
        del request
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        try:
            self._host.workspace_registry.delete(workspace_id)
        except WorkspaceRegistryError as exc:
            raise APIError(str(exc), "Workspace not found", 404) from exc
        return Response.json(WorkspaceDeleteResponse(deleted=workspace_id).model_dump(mode="json"))

    def use(self, workspace_id: str, request: Request) -> Response:
        del request
        if self._host.workspace_registry is None:
            raise APIError("workspace_not_configured", "Workspace registry is not configured", 503)
        self._host.resolve_workspace(workspace_id)
        item = self._host.workspace_registry.select(workspace_id)
        return Response.json(self._workspace_response(item))

    def status(self, workspace_id: str, request: Request) -> Response:
        del request
        item = self._host.resolve_workspace(workspace_id)
        assert self._host.workspace_registry is not None
        active = self._host.workspace_registry.active()
        response = WorkspaceStatusResponse(
            workspace=WorkspaceResponse.model_validate(item),
            active=active is not None and active["id"] == workspace_id,
        )
        return Response.json(response.model_dump(mode="json"))
