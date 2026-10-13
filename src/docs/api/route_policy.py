"""Path-shape policy for the versioned API: which routes are dynamic and which scope each needs."""

from __future__ import annotations

from urllib.parse import urlsplit

from .operations import match_operation

# First two path segments whose sub-routes are matched dynamically.
DYNAMIC_ROOTS = tuple(
    ["v2", root]
    for root in (
        "runs", "documents", "workspaces", "plugins", "artifacts", "revisions", "baselines", "templates", "issue-codes",
    )
)


def required_scope(method: str, path: str) -> str | None:
    method = method.upper()
    path = urlsplit(path).path
    static_scopes = {
        ("GET", "/v2/workspaces"): "workspaces:read",
        ("POST", "/v2/workspaces"): "workspaces:write",
        ("GET", "/v2/graph"): "graph:read",
        ("GET", "/v2/documents"): "documents:read",
        ("GET", "/v2/current-document"): "documents:read",
        ("POST", "/v2/documents"): "documents:write",
        ("POST", "/v2/documents/import"): "documents:write",
        ("POST", "/v2/documents/import/raw"): "documents:write",
        ("GET", "/v2/findings"): "findings:read",
        ("GET", "/v2/baselines"): "baselines:read",
        ("GET", "/v2/plugins"): "plugins:read",
        ("GET", "/v2/runs"): "runs:read",
        ("GET", "/v2/artifacts"): "artifacts:read",
        ("GET", "/v2/templates"): "documents:read",
        ("GET", "/v2/revisions"): "documents:read",
        ("GET", "/v2/publications"): "documents:read",
        ("POST", "/v2/runs"): "runs:write",
    }
    if (method, path) in static_scopes:
        return static_scopes[(method, path)]
    matched = match_operation(method, path)
    if matched is not None:
        return matched[0].scope
    parts = path.strip("/").split("/")
    if any(not part for part in parts):
        return None
    if parts[:2] == ["v2", "workspaces"]:
        if len(parts) == 3 and method == "GET":
            return "workspaces:read"
        if len(parts) == 3 and method == "PATCH":
            return "workspaces:write"
        if len(parts) == 3 and method == "DELETE":
            return "workspaces:write"
        if len(parts) == 4 and parts[3] == "status" and method == "GET":
            return "workspaces:read"
        if len(parts) == 4 and parts[3] == "use" and method == "POST":
            return "workspaces:write"
    if parts[:2] == ["v2", "documents"] and len(parts) in {3, 4, 5}:
        if len(parts) == 3 and method == "GET":
            return "documents:read"
        if len(parts) == 3 and method in {"PATCH", "DELETE"}:
            return "documents:write"
        if len(parts) == 4 and parts[3] == "use" and method == "POST":
            return "documents:write"
        if len(parts) == 4 and parts[3] == "runs" and method == "GET":
            return "documents:read"
        if len(parts) == 4 and parts[3] == "revisions" and method == "POST":
            return "documents:write"
        if len(parts) == 4 and parts[3] == "status" and method == "GET":
            return "documents:read"
        if len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST":
            return "documents:write"
        if len(parts) == 4 and parts[3] == "context" and method == "GET":
            return "documents:read"
        if len(parts) == 4 and parts[3] == "context" and method == "POST":
            return "documents:write"
        if len(parts) == 4 and parts[3] == "classification" and method == "GET":
            return "documents:read"
        if len(parts) == 4 and parts[3] == "classification" and method == "POST":
            return "documents:write"
        if len(parts) == 4 and parts[3] == "sections" and method == "GET":
            return "documents:read"
        if len(parts) == 5 and parts[3] == "sections" and method == "GET":
            return "documents:read"
        if len(parts) == 5 and parts[3] == "sections" and method == "PUT":
            return "documents:write"
    if parts[:2] == ["v2", "plugins"] and len(parts) == 3 and method == "GET":
        return "plugins:read"
    if parts[:2] == ["v2", "artifacts"]:
        if len(parts) == 3 and method == "GET":
            return "artifacts:read"
        if len(parts) == 4 and parts[3] == "previews" and method == "GET":
            return "artifacts:read"
    if parts[:2] == ["v2", "revisions"] and len(parts) == 3 and method == "GET":
        return "documents:read"
    if parts[:2] == ["v2", "baselines"] and len(parts) == 3 and method == "GET":
        return "baselines:read"
    if parts[:2] == ["v2", "runs"]:
        if len(parts) == 3 and method == "GET":
            return "runs:read"
        if len(parts) == 4:
            if parts[3] == "cancel" and method == "POST":
                return "runs:write"
            if parts[3] == "retry" and method == "POST":
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


def is_dynamic_route(method: str, path: str) -> bool:
    parts = path.strip("/").split("/")
    if (
        len(parts) < 3
        or any(not part for part in parts)
        or parts[:2] not in DYNAMIC_ROOTS
    ):
        return False
    if match_operation(method, path) is not None:
        return True
    if parts[:2] == ["v2", "documents"]:
        return (
            (len(parts) == 3 and method == "GET")
            or (len(parts) == 3 and method in {"PATCH", "DELETE"})
            or (len(parts) == 4 and parts[3] == "use" and method == "POST")
            or (len(parts) == 4 and parts[3] == "runs" and method == "GET")
            or (len(parts) == 4 and parts[3] == "revisions" and method == "POST")
            or (len(parts) == 4 and parts[3] in {"prepare", "build", "verify", "publish"} and method == "POST")
            or (len(parts) == 4 and parts[3] == "status" and method == "GET")
            or (len(parts) == 4 and parts[3] == "sections" and method == "GET")
            or (len(parts) == 4 and parts[3] == "context" and method in {"GET", "POST"})
            or (len(parts) == 4 and parts[3] == "classification" and method in {"GET", "POST"})
            or (len(parts) == 5 and parts[3] == "sections" and method == "GET")
            or (len(parts) == 5 and parts[3] == "sections" and method == "PUT")
        )
    if parts[:2] == ["v2", "plugins"]:
        return len(parts) == 3 and method == "GET"
    if parts[:2] == ["v2", "artifacts"]:
        return (len(parts) == 3 and method == "GET") or (len(parts) == 4 and parts[3] == "previews" and method == "GET")
    if parts[:2] == ["v2", "revisions"]:
        return len(parts) == 3 and method == "GET"
    if parts[:2] == ["v2", "baselines"]:
        return len(parts) == 3 and method == "GET"
    if len(parts) == 3 and parts[2] != "runs":
        return method == "GET"
    return (len(parts) == 4 and (
        (parts[3] == "cancel" and method == "POST")
        or (parts[3] == "retry" and method == "POST")
        or (parts[3] in {"passport", "artifacts", "progress", "findings", "graph"} and method == "GET")
    )) or (len(parts) == 5 and parts[3] == "previews" and method == "GET")
