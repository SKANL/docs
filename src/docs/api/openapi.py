"""Deterministic, dependency-free OpenAPI contract for the X20 API."""

from __future__ import annotations

import copy
import json
from typing import Any

from .document_dto import document_openapi_schemas
from .operations import OPERATIONS, available_cli_routes, component_schemas
from .workspace_dto import workspace_openapi_schemas


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(schema: dict[str, Any], description: str = "Successful response") -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def _operation(
    summary: str,
    response: dict[str, Any],
    *,
    request: dict[str, Any] | None = None,
    scopes: tuple[str, ...] = (),
    success_status: int = 200,
) -> dict[str, Any]:
    operation: dict[str, Any] = {"operationId": summary.lower().replace(" ", "_"), "summary": summary, "security": [{"bearerAuth": []}], "responses": {str(success_status): response, "400": _json_response(_ref("error"), "Invalid request"), "401": _json_response(_ref("error"), "Authentication required"), "404": _json_response(_ref("error"), "Resource not found")}}
    if request is not None:
        operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": request}}}
    if scopes:
        operation["x-rbac-scopes"] = list(scopes)
    return operation


def _parameter(name: str, location: str = "path", schema: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "in": location, "required": location == "path", "schema": schema or {"type": "string"}}


def _item_schema(name: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


def _schemas() -> dict[str, Any]:
    status = {"type": "string", "enum": ["passed", "warnings", "failed", "unverified", "queued", "running", "cancelled", "expired"]}
    return {
        "status": status,
        "error": _item_schema("error", {"code": {"type": "string"}, "message": {"type": "string"}, "details": {"type": "object"}}),
        "page": {"type": "object", "required": ["items", "next_cursor"], "properties": {"items": {"type": "array", "items": {}}, "next_cursor": {"type": ["string", "null"]}}},
        "document": _item_schema("document", {"id": {"type": "string"}, "name": {"type": "string"}, "status": _ref("status")}),
        "section": _item_schema("section", {"id": {"type": "string"}, "filename": {"type": "string"}, "body": {"type": "string"}}),
        "import_job": _item_schema("import_job", {"id": {"type": "string"}, "document_id": {"type": "string"}, "filename": {"type": "string"}, "path": {"type": "string"}, "mime_type": {"type": "string"}, "size": {"type": "integer", "minimum": 1}, "sha256": {"type": "string"}, "deduplicated": {"type": "boolean"}}),
        "stage": _item_schema("stage", {"name": {"type": "string"}, "status": _ref("status"), "progress": {"type": "number"}, "started_at": {"type": ["string", "null"], "format": "date-time"}, "finished_at": {"type": ["string", "null"], "format": "date-time"}}),
        "run": _item_schema("run", {"schema": {"type": "string", "const": "docs.x20/v1"}, "id": {"type": "string"}, "status": _ref("status"), "payload": {"type": "object"}, "created_at": {"type": "string", "format": "date-time"}}),
        "finding": _item_schema("finding", {"id": {"type": "string"}, "run_id": {"type": "string"}, "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]}, "status": _ref("status"), "message": {"type": "string"}}),
        "passport": _item_schema("passport", {"id": {"type": "string"}, "run_id": {"type": "string"}, "coverage": {"type": "number"}, "attestations": {"type": "integer"}}),
        "graph": _item_schema("graph", {"nodes": {"type": "array", "items": {"type": "object"}}, "edges": {"type": "array", "items": {"type": "object"}}}),
        "artifact": _item_schema("artifact", {"id": {"type": "string"}, "name": {"type": "string"}, "kind": {"type": "string"}, "checksum": {"type": "string"}, "status": _ref("status")}),
        "preview": _item_schema("preview", {"id": {"type": "string"}, "artifact_id": {"type": "string"}, "page": {"type": "integer"}, "url": {"type": "string", "format": "uri"}}),
        "revision": _item_schema("revision", {"id": {"type": "string"}, "message": {"type": "string"}, "author": {"type": "string"}, "status": _ref("status")}),
        "baseline": _item_schema("baseline", {"id": {"type": "string"}, "name": {"type": "string"}, "status": _ref("status"), "created_at": {"type": "string", "format": "date-time"}}),
        "plugin": _item_schema("plugin", {"id": {"type": "string"}, "name": {"type": "string"}, "version": {"type": "string"}, "enabled": {"type": "boolean"}}),
        "capability": _item_schema("capability", {
            "id": {"type": "string"}, "cli_command": {"type": "string"},
            "route": {"type": ["string", "null"]},
            "scopes": {"type": "array", "items": {"type": "string"}},
            "surface": {"type": "string", "enum": ["web+desktop", "cli"]},
            "slice": {"type": "string"},
            "status": {"type": "string", "enum": ["available", "planned", "excluded"]},
        }),
        "capability_group": _item_schema("capability_group", {
            "id": {"type": "string"},
            "capabilities": {"type": "array", "items": _ref("capability")},
        }),
        "capability_catalog": _item_schema("capability_catalog", {
            "groups": {"type": "array", "items": _ref("capability_group")},
        }),
    }


# Only routes with equivalent, implemented application behavior are advertised.
# Other CLI commands remain visible as planned inventory, never executable UI actions.
_AVAILABLE_CLI_ROUTES: dict[str, str] = {
    "workspace list": "GET /v2/workspaces",
    "workspace create": "POST /v2/workspaces",
    "workspace use": "POST /v2/workspaces/{workspace_id}/use",
    "workspace status": "GET /v2/workspaces/{workspace_id}/status",
    "workspace migrate": "POST /v2/workspaces/{workspace_id}/migrate",
    "workspace rename": "PATCH /v2/workspaces/{workspace_id}",
    "workspace delete": "DELETE /v2/workspaces/{workspace_id}",
    "doc list": "GET /v2/documents",
    "doc new": "POST /v2/documents",
    "doc current": "GET /v2/current-document",
    "doc use": "POST /v2/documents/{document_id}/use",
    "doc rename": "PATCH /v2/documents/{document_id}",
    "doc delete": "DELETE /v2/documents/{document_id}",
    "doc show": "GET /v2/documents/{document_id}",
    "context status": "GET /v2/documents/{document_id}/context",
    "context set": "POST /v2/documents/{document_id}/context",
    "document status": "GET /v2/documents/{document_id}/status",
    "document prepare": "POST /v2/documents/{document_id}/prepare",
    "document build": "POST /v2/documents/{document_id}/build",
    "document verify": "POST /v2/documents/{document_id}/verify",
    "run list": "GET /v2/runs",
    "run watch": "GET /v2/runs/{run_id}/progress",
    "run show": "GET /v2/runs/{run_id}",
    "run cancel": "POST /v2/runs/{run_id}/cancel",
    "run retry": "POST /v2/runs/{run_id}/retry",
    "template list": "GET /v2/templates",
    "document passport": "GET /v2/runs/{run_id}/passport",  # same payload `document passport` prints
    **available_cli_routes(),
}


def _cli_commands() -> list[str]:
    """Enumerate leaf commands from Typer metadata, not a second CLI list."""
    from typer.main import get_command

    from docs.cli.main import app

    def walk(group: Any, prefix: str = "") -> list[str]:
        result = []
        for name, command in group.commands.items():
            full_name = f"{prefix} {name}".strip()
            result.extend(walk(command, full_name) if hasattr(command, "commands") else [full_name])
        return result

    return sorted(walk(get_command(app)))


def _slice_for(command: str) -> str:
    group, _, action = command.partition(" ")
    if command in {"guide", "explain", "doctor", "stamp"}:
        return "S0"
    if group == "workspace" or (group == "doc" and action != "revise"):
        return "S1"
    if group in {"asset", "context", "source"} or command in {
        "doc revise", "build-section", "pack-context", "review-section",
        "review-document", "stamp-section", "document ingest", "document classify",
    }:
        return "S2"
    if group == "run" or command in {
        "document plan", "document prepare", "document run", "document build", "document verify",
    }:
        return "S3"
    if command in {"document evidence", "document passport", "document baseline", "document inspect", "document diff", "qa-docx", "apply-corrections"}:
        return "S4"
    if command in {"document package", "document publish", "document release"}:
        return "S5"
    return "S6"


# CLI commands that are terminal-only by nature; each needs the evidence for why HTTP is not the owner.
_EXCLUDED_CLI_COMMANDS: dict[str, str] = {
    "doc init": (
        "Bootstraps the process current directory (writes docs.config.json and registers it as the local "
        "workspace); over HTTP a workspace is created with POST /v2/workspaces."
    ),
}


def build_capability_catalog() -> dict[str, Any]:
    """Return all current CLI commands, advertising only exact API-backed operations."""
    paths = build_openapi_document()["paths"]
    commands = _cli_commands()
    stale = (set(_AVAILABLE_CLI_ROUTES) | set(_EXCLUDED_CLI_COMMANDS)) - set(commands)
    if stale:
        raise ValueError(f"Capability mappings reference missing CLI commands: {sorted(stale)}")
    groups: dict[str, list[dict[str, Any]]] = {}
    for command in commands:
        group = command.split(" ", 1)[0] if " " in command else "core"
        route = _AVAILABLE_CLI_ROUTES.get(command)
        scopes: list[str] = []
        if route is not None:
            method, path = route.split(" ", 1)
            scopes = list(paths[path][method.lower()].get("x-rbac-scopes", []))
        entry = {
            "id": command.replace(" ", "."), "cli_command": command,
            "route": route, "scopes": scopes, "surface": "web+desktop",
            "slice": _slice_for(command), "status": "available" if route else "planned",
        }
        if command in _EXCLUDED_CLI_COMMANDS and route is None:
            entry |= {"status": "excluded", "surface": "cli", "reason": _EXCLUDED_CLI_COMMANDS[command]}
        groups.setdefault(group, []).append(entry)
    return {"groups": [{"id": group, "capabilities": items} for group, items in groups.items()]}


def build_openapi_document() -> dict[str, Any]:
    """Return a fresh OpenAPI 3.1 document for the complete X20 contract."""
    def page(item_name: str) -> dict[str, Any]:
        return _json_response(
            {
                "allOf": [
                    _ref("page"),
                    {
                        "type": "object",
                        "properties": {"items": {"type": "array", "items": _ref(item_name)}},
                    },
                ]
            },
            "Paginated response",
        )

    document_action_request = {
        "type": "object",
        "additionalProperties": False,
        "required": ["workspace_id"],
        "properties": {
            "workspace_id": {"type": "string"},
            "run_id": {"type": "string"},
            "format": {"type": "string", "enum": ["docx", "html", "pdf"]},
            "policy": {"type": "string", "enum": ["draft", "strict", "release"]},
        },
    }
    paths: dict[str, Any] = {
        "/v2/capabilities": {
            "get": _operation("Get capability catalog", _json_response(_ref("capability_catalog"))),
        },
        "/v2/workspaces": {
            "get": _operation("List workspaces", _json_response(_ref("workspace_page")), scopes=("workspaces:read",)),
            "post": _operation("Create workspace", _json_response(_ref("workspace")), request=_ref("workspace_create_request"), scopes=("workspaces:write",), success_status=201),
        },
        "/v2/workspaces/{workspace_id}": {
            "get": _operation("Get workspace", _json_response(_ref("workspace")), scopes=("workspaces:read",)),
            "patch": _operation("Rename workspace", _json_response(_ref("workspace")), request=_ref("workspace_rename_request"), scopes=("workspaces:write",)),
            "delete": _operation("Delete workspace", _json_response(_ref("workspace_delete_response")), scopes=("workspaces:write",)),
        },
        "/v2/workspaces/{workspace_id}/use": {
            "post": _operation("Use workspace", _json_response(_ref("workspace")), scopes=("workspaces:write",)),
        },
        "/v2/workspaces/{workspace_id}/status": {
            "get": _operation("Get workspace status", _json_response(_ref("workspace_status")), scopes=("workspaces:read",)),
        },
        "/v2/workspaces/{workspace_id}/migrate": {
            "post": _operation("Migrate workspace", _json_response(_ref("workspace_migration")), request=_ref("workspace_migrate_request"), scopes=("workspaces:write",)),
        },
        "/v2/documents": {"get": _operation("List documents", page("document_summary"), scopes=("documents:read",)), "post": _operation("Create document", _json_response(_ref("document_summary")), request=_ref("document_create_request"), scopes=("documents:write",), success_status=201)},
        "/v2/current-document": {
            "get": _operation("Get current document", _json_response(_ref("document_current_response")), scopes=("documents:read",)),
        },
        "/v2/documents/import": {
            "post": _operation(
                "Import document source",
                _json_response(_ref("import_job")),
                request={
                    "type": "object",
                    "required": ["workspace_id", "filename", "content_base64"],
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "document_id": {"type": "string"},
                        "template": {"type": "string"},
                        "title": {"type": "string"},
                        "filename": {"type": "string"},
                        "content_base64": {"type": "string", "contentEncoding": "base64"},
                    },
                },
                scopes=("documents:write",),
            )
        },
        "/v2/documents/import/raw": {
            "post": _operation(
                "Import binary document source",
                _json_response(_ref("import_job")),
                request={
                    "type": "string",
                    "format": "binary",
                    "description": "Raw source bytes; workspace_id, document_id, template, and title are query parameters.",
                },
                scopes=("documents:write",),
            ),
            "parameters": [
                {**_parameter("workspace_id", "query"), "required": True},
                _parameter("document_id", "query"),
                _parameter("template", "query"),
                _parameter("title", "query"),
                _parameter("x-docs-filename", "header"),
            ],
        },
        "/v2/documents/{document_id}": {
            "get": _operation("Get document", _json_response(_ref("document")), scopes=("documents:read",)),
            "patch": _operation("Rename document", _json_response(_ref("document_summary")), request=_ref("document_rename_request"), scopes=("documents:write",)),
            "delete": _operation("Delete document", _json_response(_ref("document_delete_response")), scopes=("documents:write",)),
        },
        "/v2/documents/{document_id}/use": {
            "post": _operation("Use document", _json_response(_ref("document_summary")), scopes=("documents:write",)),
        },
        "/v2/documents/{document_id}/status": {
            "get": _operation("Get document status", _json_response({"type": "object"}), scopes=("documents:read",))
        },
        "/v2/documents/{document_id}/sections": {
            "get": _operation("List document sections", _json_response({"type": "object"}), scopes=("documents:read",))
        },
        "/v2/documents/{document_id}/sections/{section_id}": {
            "get": _operation("Get document section", _json_response(_ref("section")), scopes=("documents:read",)),
            "put": _operation("Update document section", _json_response(_ref("revision")), request={"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}, "request": {"type": "string"}}}, scopes=("documents:write",))
        },
        "/v2/documents/{document_id}/context": {
            "get": _operation("Get document context status", _json_response({"type": "object"}), scopes=("documents:read",)),
            "post": _operation(
                "Set document context value",
                _json_response({"type": "object"}),
                request={
                    "type": "object",
                    "required": ["topic", "value"],
                    "properties": {
                        "topic": {"type": "string"},
                        "field": {"type": "string"},
                        "value": {"type": "string"},
                    },
                },
                scopes=("documents:write",),
            ),
        },
        "/v2/documents/{document_id}/classification": {
            "get": _operation("Get source classification queue", _json_response({"type": "object"}), scopes=("documents:read",)),
            "post": _operation(
                "Confirm source classification",
                _json_response({"type": "object"}),
                request={
                    "type": "object",
                    "required": ["relative_path", "confirmed_role"],
                    "properties": {
                        "relative_path": {"type": "string"},
                        "confirmed_role": {"type": "string", "enum": ["evidence", "example", "normative"]},
                    },
                },
                scopes=("documents:write",),
            ),
        },
        "/v2/documents/{document_id}/runs": {
            "get": _operation("List document runs", page("run"), scopes=("documents:read",))
        },
        "/v2/documents/{document_id}/prepare": {"post": _operation("Prepare document", _json_response(_ref("document")), request=document_action_request, scopes=("documents:write",))},
        "/v2/documents/{document_id}/build": {"post": _operation("Build document", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v2/documents/{document_id}/verify": {"post": _operation("Verify document", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v2/documents/{document_id}/publish": {"post": _operation("Enqueue document-publish pipeline run (asynchronous; for a direct synchronous publish of one artifact use POST .../publications)", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v2/documents/{document_id}/revisions": {
            "post": _operation("Create document revision", _json_response(_ref("RevisionResponse")), request=_ref("RevisionRequest"), scopes=("documents:write",), success_status=201)
        },
        "/v2/graph": {
            "get": _operation("Get graph", _json_response(_ref("graph")), scopes=("graph:read",)),
            "parameters": [
                {
                    "name": "mode",
                    "in": "query",
                    "description": "Optional graph read-model query mode. Omit it to return the complete graph.",
                    "schema": {
                        "type": "string",
                        "enum": [
                            "claims_without_evidence",
                            "findings_affected_by_revision",
                            "artifacts_derived_from_input",
                            "unused_references",
                            "unmet_requirements",
                        ],
                    },
                },
                {
                    "name": "query",
                    "in": "query",
                    "description": "Review Studio graph query alias. Cannot be combined with mode.",
                    "schema": {
                        "type": "string",
                        "enum": [
                            "claims_without_evidence",
                            "findings_affected_by_revision",
                            "artifacts_derived_from_input",
                            "unused_references",
                            "unmet_requirements",
                        ],
                    },
                },
                {
                    "name": "id",
                    "in": "query",
                    "description": "Identifier required by findings_affected_by_revision or artifacts_derived_from_input when query is used.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "revision_id",
                    "in": "query",
                    "description": "Revision identifier required by findings_affected_by_revision.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "input_id",
                    "in": "query",
                    "description": "Input identifier required by artifacts_derived_from_input.",
                    "schema": {"type": "string"},
                },
                {"name": "workspace_id", "in": "query", "schema": {"type": "string"}},
            ],
        },
        "/v2/findings": {"get": _operation("List findings", page("finding"), scopes=("findings:read",))},
        "/v2/artifacts": {"get": _operation("List artifacts", page("artifact"), scopes=("artifacts:read",))},
        "/v2/templates": {"get": _operation("List templates", page("document"), scopes=("documents:read",))},
        "/v2/revisions": {"get": _operation("List revisions", page("revision"), scopes=("documents:read",))},
        "/v2/publications": {"get": _operation("List publications", page("baseline"), scopes=("documents:read",))},
        "/v2/runs": {
            "get": _operation("List runs", page("run"), scopes=("runs:read",)),
            "post": _operation("Create run", _json_response(_ref("run")), request={"$ref": "#/components/schemas/run"}, scopes=("runs:write",)),
        },
        "/v2/runs/{run_id}": {"get": _operation("Get run", _json_response(_ref("run")), scopes=("runs:read",))},
        "/v2/runs/{run_id}/cancel": {"post": _operation("Cancel run", _json_response(_ref("run")), scopes=("runs:write",))},
        "/v2/runs/{run_id}/retry": {"post": _operation("Retry run", _json_response(_ref("run")), scopes=("runs:write",))},
        "/v2/runs/{run_id}/passport": {"get": _operation("Get run passport", _json_response(_ref("passport")), scopes=("passport:read",))},
        "/v2/runs/{run_id}/artifacts": {"get": _operation("List run artifacts", page("artifact"), scopes=("artifacts:read",))},
        "/v2/runs/{run_id}/progress": {"get": _operation("Stream run progress", {"description": "Server-sent progress events", "content": {"text/event-stream": {"schema": {"type": "string"}}}}, scopes=("runs:read",))},
        "/v2/artifacts/{artifact_id}": {"get": _operation("Get artifact", _json_response(_ref("artifact")), scopes=("artifacts:read",))},
        "/v2/artifacts/{artifact_id}/previews": {"get": _operation("List artifact previews", page("preview"), scopes=("artifacts:read",))},
        "/v2/revisions/{revision_id}": {"get": _operation("Get revision", _json_response(_ref("revision")), scopes=("documents:read",))},
        "/v2/baselines": {"get": _operation("List baselines", page("baseline"), scopes=("baselines:read",))},
        "/v2/baselines/{baseline_id}": {"get": _operation("Get baseline", _json_response(_ref("baseline")), scopes=("baselines:read",))},
        "/v2/plugins": {"get": _operation("List plugins", page("plugin"), scopes=("plugins:read",))},
        "/v2/plugins/{plugin_id}": {"get": _operation("Get plugin", _json_response(_ref("plugin")), scopes=("plugins:read",))},
    }
    for plugin_path in ("/v2/plugins", "/v2/plugins/{plugin_id}"):
        paths[plugin_path]["get"]["description"] = (
            "Plugins are read-only by design: manifests are inspected and never executed, "
            "so no write method is routed."
        )
    paths["/v2/runs/{run_id}/graph"] = copy.deepcopy(paths["/v2/graph"])
    paths["/v2/runs/{run_id}/findings"] = {"get": _operation("List run findings", page("finding"), scopes=("findings:read",))}
    paths["/v2/runs/{run_id}/previews/{name}"] = {"get": _operation("Get run preview", {"description": "PNG preview image", "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}, scopes=("artifacts:read",))}
    paths["/v2/runs/{run_id}/graph"]["get"]["operationId"] = "get_run_graph"
    paths["/v2/runs/{run_id}/graph"]["get"]["summary"] = "Get run graph"
    for operation in OPERATIONS:
        paths.setdefault(operation.path, {})[operation.method.lower()] = _operation(
            operation.summary,
            _json_response(operation.response_ref()),
            request=operation.request_ref(),
            scopes=(operation.scope,),
            success_status=operation.success_status,
        )
    paged_paths = {"/v2/documents", "/v2/findings", "/v2/artifacts", "/v2/templates", "/v2/revisions", "/v2/publications", "/v2/runs", "/v2/runs/{run_id}/artifacts", "/v2/runs/{run_id}/findings", "/v2/artifacts/{artifact_id}/previews", "/v2/baselines", "/v2/plugins"}
    workspace_scoped = {
        "/v2/documents", "/v2/current-document", "/v2/documents/{document_id}", "/v2/documents/{document_id}/use", "/v2/documents/{document_id}/status",
        "/v2/documents/{document_id}/sections", "/v2/documents/{document_id}/sections/{section_id}",
        "/v2/documents/{document_id}/context", "/v2/documents/{document_id}/classification",
        "/v2/documents/{document_id}/runs", "/v2/documents/{document_id}/prepare",
        "/v2/documents/{document_id}/build", "/v2/documents/{document_id}/verify",
        "/v2/documents/{document_id}/publish", "/v2/documents/{document_id}/revisions",
        "/v2/graph", "/v2/findings", "/v2/artifacts", "/v2/templates", "/v2/revisions",
        "/v2/publications", "/v2/runs", "/v2/runs/{run_id}", "/v2/runs/{run_id}/cancel",
        "/v2/runs/{run_id}/retry", "/v2/runs/{run_id}/passport", "/v2/runs/{run_id}/artifacts",
        "/v2/runs/{run_id}/progress", "/v2/runs/{run_id}/graph", "/v2/runs/{run_id}/findings",
        "/v2/runs/{run_id}/previews/{name}", "/v2/artifacts/{artifact_id}",
        "/v2/artifacts/{artifact_id}/previews", "/v2/revisions/{revision_id}",
        "/v2/baselines", "/v2/baselines/{baseline_id}",
    } | {operation.path for operation in OPERATIONS}
    for path, item in paths.items():
        parameters = []
        for segment in ("document_id", "run_id", "artifact_id", "revision_id", "baseline_id", "plugin_id", "workspace_id", "asset_name", "topic_id", "template_name"):
            if "{" + segment + "}" in path:
                parameters.append(_parameter(segment))
        parameters.extend(item.get("parameters", ()))
        if path in workspace_scoped:
            workspace_parameter = next((p for p in parameters if p["name"] == "workspace_id"), None)
            if workspace_parameter is None:
                parameters.append({**_parameter("workspace_id", "query"), "required": True})
            else:
                workspace_parameter["required"] = True
        elif path in {"/v2/plugins", "/v2/plugins/{plugin_id}"}:
            parameters.append(_parameter("workspace_id", "query"))
        if path in paged_paths:
            parameters.extend([_parameter("limit", "query", {"type": "integer", "minimum": 1, "maximum": 100}), _parameter("cursor", "query", {"type": "string"})])
        if parameters:
            item["parameters"] = parameters
    schemas = _schemas()
    schemas["capability"]["properties"]["reason"] = {"type": "string"}  # optional: only `excluded` rows carry it
    schemas.update(workspace_openapi_schemas())
    schemas.update(document_openapi_schemas())
    schemas.update(component_schemas())
    return {"openapi": "3.1.0", "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema", "info": {"title": "X20 API", "version": "2.0.0"}, "servers": [{"url": "/"}], "security": [{"bearerAuth": []}], "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}, "schemas": schemas}}


def canonical_json(value: Any) -> str:
    """Serialize JSON canonically for stable hashes, snapshots, and transport."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["build_openapi_document", "canonical_json"]
