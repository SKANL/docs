"""Deterministic, dependency-free OpenAPI contract for the X20 API."""

from __future__ import annotations

import copy
import json
from typing import Any


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
    operation: dict[str, Any] = {"operationId": summary.lower().replace(" ", "_"), "summary": summary, "security": [{"bearerAuth": []}, {"apiKeyAuth": []}], "responses": {str(success_status): response, "400": _json_response(_ref("error"), "Invalid request"), "401": _json_response(_ref("error"), "Authentication required"), "404": _json_response(_ref("error"), "Resource not found")}}
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
        "workspace": _item_schema("workspace", {"id": {"type": "string"}, "name": {"type": "string"}, "root": {"type": "string"}}),
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
    }


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
        "/v1/workspaces": {
            "get": _operation("List workspaces", page("workspace"), scopes=("workspaces:read",)),
            "post": _operation("Create workspace", _json_response(_ref("workspace")), request={"$ref": "#/components/schemas/workspace"}, scopes=("workspaces:write",)),
        },
        "/v1/workspaces/{workspace_id}": {
            "get": _operation("Get workspace", _json_response(_ref("workspace")), scopes=("workspaces:read",)),
            "patch": _operation("Rename workspace", _json_response(_ref("workspace")), request={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}, scopes=("workspaces:write",)),
            "delete": _operation("Delete workspace", _json_response({"type": "object"}), scopes=("workspaces:write",)),
        },
        "/v1/workspaces/{workspace_id}/select": {
            "post": _operation("Select workspace", _json_response(_ref("workspace")), scopes=("workspaces:write",)),
        },
        "/v1/documents": {"get": _operation("List documents", page("document"), scopes=("documents:read",)), "post": _operation("Create document", _json_response(_ref("document")), scopes=("documents:write",))},
        "/v1/documents/import": {
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
        "/v1/documents/import/raw": {
            "post": _operation(
                "Import binary document source",
                _json_response(_ref("import_job")),
                request={
                    "type": "string",
                    "format": "binary",
                    "description": "Raw source bytes; workspace_id, document_id, template, and title are query parameters.",
                },
                scopes=("documents:write",),
            )
        },
        "/v1/documents/{document_id}": {
            "get": _operation("Get document", _json_response(_ref("document")), scopes=("documents:read",))
        },
        "/v1/documents/{document_id}/status": {
            "get": _operation("Get document status", _json_response({"type": "object"}), scopes=("documents:read",))
        },
        "/v1/documents/{document_id}/sections": {
            "get": _operation("List document sections", _json_response({"type": "object"}), scopes=("documents:read",))
        },
        "/v1/documents/{document_id}/sections/{section_id}": {
            "get": _operation("Get document section", _json_response(_ref("section")), scopes=("documents:read",)),
            "put": _operation("Update document section", _json_response(_ref("revision")), request={"type": "object", "required": ["body"], "properties": {"body": {"type": "string"}, "request": {"type": "string"}}}, scopes=("documents:write",))
        },
        "/v1/documents/{document_id}/context": {
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
        "/v1/documents/{document_id}/classification": {
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
        "/v1/documents/{document_id}/runs": {
            "get": _operation("List document runs", page("run"), scopes=("documents:read",))
        },
        "/v1/documents/{document_id}/prepare": {"post": _operation("Prepare document", _json_response(_ref("document")), request=document_action_request, scopes=("documents:write",))},
        "/v1/documents/{document_id}/build": {"post": _operation("Build document", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v1/documents/{document_id}/verify": {"post": _operation("Verify document", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v1/documents/{document_id}/publish": {"post": _operation("Publish document", _json_response(_ref("run")), request=document_action_request, scopes=("documents:write",), success_status=202)},
        "/v1/documents/{document_id}/revisions": {
            "post": _operation("Create document revision", _json_response(_ref("revision")), scopes=("documents:write",))
        },
        "/v1/graph": {
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
        "/v1/findings": {"get": _operation("List findings", page("finding"), scopes=("findings:read",))},
        "/v1/artifacts": {"get": _operation("List artifacts", page("artifact"), scopes=("artifacts:read",))},
        "/v1/templates": {"get": _operation("List templates", page("document"), scopes=("documents:read",))},
        "/v1/revisions": {"get": _operation("List revisions", page("revision"), scopes=("documents:read",))},
        "/v1/publications": {"get": _operation("List publications", page("baseline"), scopes=("documents:read",))},
        "/v1/runs": {
            "get": _operation("List runs", page("run"), scopes=("runs:read",)),
            "post": _operation("Create run", _json_response(_ref("run")), request={"$ref": "#/components/schemas/run"}, scopes=("runs:write",)),
        },
        "/v1/runs/{run_id}": {"get": _operation("Get run", _json_response(_ref("run")), scopes=("runs:read",))},
        "/v1/runs/{run_id}/cancel": {"post": _operation("Cancel run", _json_response(_ref("run")), scopes=("runs:write",))},
        "/v1/runs/{run_id}/retry": {"post": _operation("Retry run", _json_response(_ref("run")), scopes=("runs:write",))},
        "/v1/runs/{run_id}/passport": {"get": _operation("Get run passport", _json_response(_ref("passport")), scopes=("passport:read",))},
        "/v1/runs/{run_id}/artifacts": {"get": _operation("List run artifacts", page("artifact"), scopes=("artifacts:read",))},
        "/v1/runs/{run_id}/progress": {"get": _operation("Stream run progress", {"description": "Server-sent progress events", "content": {"text/event-stream": {"schema": {"type": "string"}}}}, scopes=("runs:read",))},
        "/v1/artifacts/{artifact_id}": {"get": _operation("Get artifact", _json_response(_ref("artifact")), scopes=("artifacts:read",))},
        "/v1/artifacts/{artifact_id}/previews": {"get": _operation("List artifact previews", page("preview"), scopes=("artifacts:read",))},
        "/v1/revisions/{revision_id}": {"get": _operation("Get revision", _json_response(_ref("revision")), scopes=("documents:read",))},
        "/v1/baselines": {"get": _operation("List baselines", page("baseline"), scopes=("baselines:read",)), "post": _operation("Create baseline", _json_response(_ref("baseline")), request={"$ref": "#/components/schemas/baseline"}, scopes=("baselines:write",))},
        "/v1/baselines/{baseline_id}": {"get": _operation("Get baseline", _json_response(_ref("baseline")), scopes=("baselines:read",))},
        "/v1/baselines/{baseline_id}/promote": {"post": _operation("Promote baseline", _json_response(_ref("baseline")), scopes=("baselines:write",))},
        "/v1/baselines/promotions": {
            "post": _operation(
                "Promote baseline from collection",
                _json_response(_ref("baseline")),
                request={
                    "type": "object",
                    "properties": {"baseline_id": {"type": "string"}, "id": {"type": "string"}},
                    "anyOf": [{"required": ["baseline_id"]}, {"required": ["id"]}],
                },
                scopes=("baselines:write",),
            )
        },
        "/v1/plugins": {"get": _operation("List plugins", page("plugin"), scopes=("plugins:read",))},
        "/v1/plugins/{plugin_id}": {"get": _operation("Get plugin", _json_response(_ref("plugin")), scopes=("plugins:read",))},
    }
    paths["/v1/runs/{run_id}/graph"] = copy.deepcopy(paths["/v1/graph"])
    paths["/v1/runs/{run_id}/graph"]["get"]["operationId"] = "get_run_graph"
    paths["/v1/runs/{run_id}/graph"]["get"]["summary"] = "Get run graph"
    paged_paths = {"/v1/documents", "/v1/findings", "/v1/artifacts", "/v1/templates", "/v1/revisions", "/v1/publications", "/v1/runs", "/v1/runs/{run_id}/artifacts", "/v1/artifacts/{artifact_id}/previews", "/v1/baselines", "/v1/plugins"}
    for path, item in paths.items():
        parameters = []
        for segment in ("document_id", "run_id", "artifact_id", "revision_id", "baseline_id", "plugin_id"):
            if "{" + segment + "}" in path:
                parameters.append(_parameter(segment))
        parameters.extend(item.get("parameters", ()))
        if path in paged_paths:
            parameters.extend([_parameter("limit", "query", {"type": "integer", "minimum": 1, "maximum": 100}), _parameter("cursor", "query", {"type": "string"}), _parameter("workspace_id", "query", {"type": "string"})])
        if parameters:
            item["parameters"] = parameters
    return {"openapi": "3.1.0", "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema", "info": {"title": "X20 API", "version": "1.0.0"}, "servers": [{"url": "/"}], "security": [{"bearerAuth": []}, {"apiKeyAuth": []}], "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}, "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}, "schemas": _schemas()}}


def canonical_json(value: Any) -> str:
    """Serialize JSON canonically for stable hashes, snapshots, and transport."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["build_openapi_document", "canonical_json"]
