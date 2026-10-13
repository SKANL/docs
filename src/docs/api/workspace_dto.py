"""Strict transport DTOs for workspace HTTP endpoints and OpenAPI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class WorkspaceDTO(BaseModel):
    """Base model that makes the workspace transport boundary explicit."""

    model_config = ConfigDict(extra="forbid", strict=True)


class WorkspaceResponse(WorkspaceDTO):
    id: str
    name: str
    root: str


class WorkspacePage(WorkspaceDTO):
    items: list[WorkspaceResponse]
    next_cursor: str | None = None


class WorkspaceCreateRequest(WorkspaceDTO):
    name: str


class WorkspaceRenameRequest(WorkspaceDTO):
    name: str


class WorkspaceDeleteResponse(WorkspaceDTO):
    deleted: str


class WorkspaceStatusResponse(WorkspaceDTO):
    workspace: WorkspaceResponse
    active: bool


class WorkspaceMigrateRequest(WorkspaceDTO):
    apply: bool = False


class WorkspaceMigrationResponse(WorkspaceDTO):
    source_workspace_id: str
    detected_format: str
    ready: bool
    published: bool
    workspace: WorkspaceResponse | None = None
    errors: list[str]


def workspace_openapi_schemas() -> dict[str, dict[str, Any]]:
    """Return component schemas generated from the runtime DTO definitions."""
    page = WorkspacePage.model_json_schema(ref_template="#/components/schemas/{model}")
    page.pop("$defs", None)
    page["properties"]["items"]["items"] = {"$ref": "#/components/schemas/workspace"}
    status = WorkspaceStatusResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    status.pop("$defs", None)
    status["properties"]["workspace"] = {"$ref": "#/components/schemas/workspace"}
    migration = WorkspaceMigrationResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    migration.pop("$defs", None)
    migration["properties"]["workspace"] = {"anyOf": [{"$ref": "#/components/schemas/workspace"}, {"type": "null"}], "default": None}
    return {
        "workspace": WorkspaceResponse.model_json_schema(),
        "workspace_page": page,
        "workspace_create_request": WorkspaceCreateRequest.model_json_schema(),
        "workspace_rename_request": WorkspaceRenameRequest.model_json_schema(),
        "workspace_delete_response": WorkspaceDeleteResponse.model_json_schema(),
        "workspace_status": status,
        "workspace_migrate_request": WorkspaceMigrateRequest.model_json_schema(),
        "workspace_migration": migration,
    }


__all__ = [
    "WorkspaceCreateRequest",
    "WorkspaceDeleteResponse",
    "WorkspaceMigrateRequest",
    "WorkspaceMigrationResponse",
    "WorkspacePage",
    "WorkspaceRenameRequest",
    "WorkspaceResponse",
    "WorkspaceStatusResponse",
    "workspace_openapi_schemas",
]
