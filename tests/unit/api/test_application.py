import io
import json
import threading
from pathlib import Path

import pytest

from docs.api.application import X20Application
from docs.api.auth import Principal
from docs.api.enterprise import TokenBucketRateLimiter
from docs.api.http import APIError, Request, Response, Router
from docs.api.oidc import scope_policy
from docs.api.openapi import build_openapi_document, canonical_json
from docs.application.workspaces import WorkspaceRegistry
from docs.domain.runtime_records import Artifact, Graph, Passport, Run
from docs.domain.semantic_graph import SemanticEdge, SemanticGraph, SemanticNode


class Runs:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.id] = item

    def get(self, key):
        return self.items.get(key)

    def list(self):
        return list(self.items.values())


class Queue:
    def __init__(self):
        self.calls = []
        self.cancel_calls = []

    def enqueue(self, job_id, payload):
        self.calls.append((job_id, payload))

    def cancel(self, job_id):
        self.cancel_calls.append(job_id)


class Passports:
    def get(self, key):
        return Passport(key, ({"ok": True},))


class Artifacts:
    def list(self):
        return []

    def list_for_run(self, key):
        return [Artifact("a1", key, "docx", "sha")]

    def get(self, key):
        return None


class Graphs:
    def get(self):
        return Graph(("r1", "a1"), (("r1", "a1"),))


def body(response):
    return json.loads(response.body)


ALL_SCOPES = frozenset({
    "documents:read", "documents:write", "runs:read", "runs:write", "findings:read",
    "artifacts:read", "graph:read", "passport:read", "baselines:read", "baselines:write",
    "plugins:read", "publication:write",
})


def app(router=None):
    return X20Application(
        run_store=Runs(),
        queue=Queue(),
        passport_store=Passports(),
        artifact_store=Artifacts(),
        graph_store=Graphs(),
        documents=[{"id": "d1", "owner": "ada"}],
        findings=[{"run_id": "r1", "severity": "error"}],
        router=router,
    )


def test_application_rejects_preexisting_dynamic_route_collision_at_construction():
    router = Router()
    router.route("GET", "/v2/runs/r1")(lambda _: Response.json({"owner": "other"}))

    with pytest.raises(ValueError, match="GET /v2/runs/r1"):
        X20Application(
            run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
            graph_store=Graphs(), router=router,
        )


def test_openapi_endpoint_returns_deterministic_json_without_workspace():
    application = app()

    first = application.dispatch(Request("GET", "/v2/openapi.json"))
    second = application.dispatch(Request("GET", "/v2/openapi.json"))

    assert first.status == second.status == 200
    assert first.headers["content-type"] == "application/json"
    assert first.body == second.body == canonical_json(build_openapi_document()).encode()


def test_application_exposes_only_the_v2_openapi_endpoint():
    application = app()

    assert application.dispatch(Request("GET", "/v2/openapi.json")).status == 200
    assert application.dispatch(Request("GET", "/v1/openapi.json")).status == 404


def test_v2_workspace_contract_has_no_server_active_selection_or_fallback(tmp_path):
    root = tmp_path / "workspace"
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    workspace = registry.create("Workspace", root)
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=registry,
    )

    listed = body(application.dispatch(Request("GET", "/v2/workspaces")))
    assert "active" not in listed
    assert application.dispatch(Request("POST", f"/v2/workspaces/{workspace['id']}/select")).status == 404
    assert application.dispatch(Request("GET", "/v1/workspaces")).status == 404
    assert application.dispatch(Request("GET", "/v2/documents/d1/status")).status == 400
    assert application.dispatch(Request("GET", f"/v2/documents/d1/status?workspace_id={workspace['id']}")).status == 404


def test_workspace_transport_dtos_are_strict_and_serialize_the_canonical_shapes(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "state" / "registry.json")
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=registry,
        managed_workspace_root=tmp_path / "managed-workspaces",
    )

    created = application.dispatch(Request("POST", "/v2/workspaces", body={"name": "Managed"}))
    workspace = body(created)
    listed = application.dispatch(Request("GET", "/v2/workspaces"))
    renamed = application.dispatch(
        Request("PATCH", f"/v2/workspaces/{workspace['id']}", body={"name": "Renamed"})
    )
    fetched = application.dispatch(Request("GET", f"/v2/workspaces/{workspace['id']}"))
    deleted = application.dispatch(Request("DELETE", f"/v2/workspaces/{workspace['id']}"))

    assert created.status == 201
    assert set(workspace) == {"id", "name", "root"}
    assert list(Path(workspace["root"]).glob("templates/*.json"))
    assert body(listed) == {"items": [workspace], "next_cursor": None}
    assert body(renamed) == {**workspace, "name": "Renamed"}
    assert body(fetched) == body(renamed)
    assert body(deleted) == {"deleted": workspace["id"]}


@pytest.mark.parametrize("method,path,payload", [
    ("POST", "/v2/workspaces", {"name": "Managed", "root": "/client-controlled"}),
    ("POST", "/v2/workspaces", {"name": 1}),
    ("PATCH", "/v2/workspaces/missing", {"name": "Renamed", "unexpected": True}),
    ("PATCH", "/v2/workspaces/missing", {"name": 1}),
])
def test_workspace_transport_dtos_reject_unknown_fields_and_non_string_names(tmp_path, method, path, payload):
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=WorkspaceRegistry(tmp_path / "registry.json"),
        managed_workspace_root=tmp_path / "managed-workspaces",
    )

    response = application.dispatch(Request(method, path, body=payload))

    assert response.status == 400
    assert body(response)["error"]["code"] == "invalid_request"


def test_workspace_creation_allocates_under_managed_root_and_rejects_client_root(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "state" / "registry.json")
    managed_root = tmp_path / "managed-workspaces"
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=registry, managed_workspace_root=managed_root,
    )

    created = application.dispatch(Request("POST", "/v2/workspaces", body={"name": "Managed"}))
    outside_root = tmp_path / "attacker-controlled"
    rejected = application.dispatch(Request("POST", "/v2/workspaces", body={"name": "External", "root": str(outside_root)}))

    assert created.status == 201
    assert Path(body(created)["root"]).parent == managed_root
    assert rejected.status == 400
    assert not outside_root.exists()


@pytest.mark.parametrize("method,path", [
    ("GET", "/v2/documents"), ("GET", "/v2/findings"), ("GET", "/v2/artifacts"),
    ("GET", "/v2/runs"), ("GET", "/v2/runs/r1"), ("GET", "/v2/baselines"),
    ("GET", "/v2/baselines/b1"), ("GET", "/v2/revisions"),
    ("GET", "/v2/revisions/rev1"), ("GET", "/v2/publications"),
    ("GET", "/v2/templates"), ("GET", "/v2/graph"),
])
def test_workspace_content_routes_fail_closed_without_explicit_workspace(tmp_path, method, path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    registry.create("Workspace", tmp_path / "workspace")
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=registry,
    )

    response = application.dispatch(Request(method, path))

    assert response.status == 400
    assert body(response)["error"]["code"] == "workspace_required"


def test_document_collection_rejects_invalid_workspace_before_reading_store(tmp_path):
    class WorkspaceDocuments:
        def __init__(self):
            self.calls = []

        def list_for_workspace(self, root):
            self.calls.append(root)
            return []

    registry = WorkspaceRegistry(tmp_path / "registry.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    Path(workspace["root"], "workspace.json").unlink()
    documents = WorkspaceDocuments()
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), document_store=documents, workspace_registry=registry,
    )

    response = application.dispatch(
        Request("GET", f"/v2/documents?workspace_id={workspace['id']}")
    )

    assert response.status == 409
    assert body(response)["error"]["code"] == "workspace_marker_missing"
    assert documents.calls == []


def test_create_run_rejects_invalid_workspace_before_writing_or_enqueuing(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    Path(workspace["root"], "workspace.json").write_text(
        '{"schema":"docs.workspace/v2"}', encoding="utf-8"
    )
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), workspace_registry=registry,
    )

    response = application.dispatch(
        Request("POST", "/v2/runs", body={"workspace_id": workspace["id"]})
    )

    assert response.status == 409
    assert body(response)["error"]["code"] == "workspace_schema_unsupported"
    assert application.run_store.items == {}
    assert application.queue.calls == []


def test_contract_census_distinguishes_live_routes_from_openapi_only_operations():
    application = app()
    paths = build_openapi_document()["paths"]

    # Runtime-only run capabilities are part of the canonical schema.
    assert application._dynamic_handler("GET", "/v2/runs/r1/findings") is not None
    assert application._dynamic_handler("GET", "/v2/runs/r1/previews/a1") is not None
    assert "/v2/runs/{run_id}/findings" in paths
    assert "/v2/runs/{run_id}/previews/{name}" in paths

    # Unsupported mutation operations are not part of the public contract.
    assert "post" not in paths["/v2/baselines"]
    assert "/v2/baselines/{baseline_id}/promote" not in paths
    assert "/v2/workspaces/{workspace_id}/select" not in paths
    assert application._dynamic_handler("POST", "/v2/baselines") is None
    assert application._dynamic_handler("POST", "/v2/baselines/b1/promote") is None


def test_openapi_documents_owned_document_scope_operations():
    paths = build_openapi_document()["paths"]

    assert paths["/v2/documents/{document_id}"]["get"]["x-rbac-scopes"] == ["documents:read"]
    assert paths["/v2/documents/{document_id}/runs"]["get"]["x-rbac-scopes"] == ["documents:read"]
    assert paths["/v2/documents/{document_id}/revisions"]["post"]["x-rbac-scopes"] == ["documents:write"]


def section_app(tmp_path, revision_service=None):
    root = tmp_path / "workspace"
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    workspace = registry.create("Sections", root)
    registry.select(workspace["id"])
    document_root = root / "documents" / "d1"
    (document_root / "sections").mkdir(parents=True)
    (document_root / "document.json").write_text('{"id":"d1","title":"D1"}', encoding="utf-8")
    (document_root / "sections" / "intro.md").write_text("Original", encoding="utf-8")
    return X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), documents=[{"id": "d1"}], workspace_registry=registry,
        revision_service=revision_service,
    )


def test_document_section_routes_list_get_and_reject_traversal(tmp_path):
    application = section_app(tmp_path)

    workspace_id = application.workspace_registry.list()[0]["id"]
    listed = application.dispatch(Request("GET", f"/v2/documents/d1/sections?workspace_id={workspace_id}"))
    fetched = application.dispatch(Request("GET", f"/v2/documents/d1/sections/intro?workspace_id={workspace_id}"))
    with pytest.raises(APIError, match="Invalid section identifier"):
        application._document_section("d1", "../document", Request("GET", f"/v2/documents/d1/sections/../document?workspace_id={workspace_id}"))

    assert body(listed)["items"] == [{"id": "intro", "filename": "intro.md", "body": "Original"}]
    assert body(fetched)["body"] == "Original"


def test_put_document_section_uses_configured_revision_service(tmp_path):
    calls = []

    class RevisionService:
        def revise(self, document_id, revision):
            calls.append((document_id, revision))
            return {"diff_path": "sections/_revisions/intro.1.diff"}

    application = section_app(tmp_path, RevisionService())
    workspace_id = application.workspace_registry.list()[0]["id"]
    response = application.dispatch(
        Request("PUT", f"/v2/documents/d1/sections/intro?workspace_id={workspace_id}", body={"body": "Revised", "request": "Clarify"})
    )

    assert response.status == 200
    assert calls == [("d1", {"target_id": "intro", "new_body": "Revised", "request": "Clarify"})]


@pytest.mark.parametrize(("path", "status", "code"), [("/v2/documents", 400, "workspace_required"), ("/v2/documents?workspace_id=w1", 503, "workspace_not_configured"), ("/v2/documents?owner=ada&limit=1", 400, "workspace_required"), ("/v2/documents?limit=nope", 400, "workspace_required")])
def test_document_collection_fails_closed_without_workspace_registry(path, status, code):
    with pytest.raises(APIError) as error:
        app()._documents(Request("GET", path))
    assert (error.value.status, error.value.code) == (status, code)


def test_list_runs_returns_empty_page_from_injected_store():
    response = app().dispatch(Request("GET", "/v2/runs"))

    assert response.status == 200
    assert body(response) == {"items": [], "next_cursor": None}


def test_list_runs_returns_records_from_injected_store():
    application = app()
    application.run_store.put(Run("run-1", payload={"document_id": "d1"}, created_at="2026-01-01T00:00:00+00:00"))

    response = application.dispatch(Request("GET", "/v2/runs"))

    assert response.status == 200
    assert body(response)["items"] == [application.run_store.get("run-1").to_dict()]


def test_list_runs_filters_by_workspace_id_inside_run_payload():
    application = app()
    run = Run("run-workspace-one", payload={"document_id": "d1", "workspace_id": "workspace-one"}, created_at="2026-01-01T00:00:00+00:00")
    other = Run("run-workspace-two", payload={"document_id": "d2", "workspace_id": "workspace-two"}, created_at="2026-01-02T00:00:00+00:00")
    application.run_store.put(run)
    application.run_store.put(other)

    response = application.dispatch(Request("GET", "/v2/runs?workspace_id=workspace-one"))

    assert response.status == 200
    assert body(response)["items"] == [run.to_dict()]


@pytest.mark.parametrize("path", ["/v2/artifacts", "/v2/templates", "/v2/revisions", "/v2/publications"])
def test_review_studio_collection_routes_return_empty_pages(path):
    response = app().dispatch(Request("GET", path))

    assert response.status == 200
    assert body(response) == {"items": [], "next_cursor": None}


def test_auth_refresh_preserves_unrelated_router_routes():
    router = Router()

    def unrelated(_):
        return Response.json({"owner": "other"})

    router.route("GET", "/v2/other")(unrelated)
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), router=router,
    )
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None
    application.dispatch(Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"}))

    assert body(router.dispatch(Request("GET", "/v2/other"))) == {"owner": "other"}


def test_post_run_is_idempotent_and_enqueues_once():
    application = app()
    request = Request("POST", "/v2/runs", body={"id": "r1", "document_id": "d1"}, headers={"Idempotency-Key": "same"})
    first = application.dispatch(request)
    second = application.dispatch(request)
    assert first.status == second.status == 201
    assert body(first)["id"] == body(second)["id"] == "r1"
    assert len(application.queue.calls) == 1


def test_post_run_binds_ownership_from_authenticated_principal():
    application = app()
    principal = Principal(
        "user-1",
        frozenset({"runs:write"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request(
            "POST",
            "/v2/runs",
            headers={"Authorization": "Bearer ok"},
            body={
                "id": "r1",
                "owner_subject": "attacker",
                "tenant_id": "tenant-b",
                "organization_id": "org-b",
            },
        )
    )

    payload = body(response)["payload"]
    assert payload["owner_subject"] == "user-1"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["organization_id"] == "org-a"
    assert application.queue.calls[0][1] == payload


def test_post_run_rejects_authenticated_principal_without_tenant_identity():
    application = app()
    application.auth = lambda token: Principal("legacy", frozenset({"runs:write"}))

    response = application.dispatch(
        Request(
            "POST",
            "/v2/runs",
            headers={"Authorization": "Bearer ok"},
            body={"id": "r1"},
        )
    )

    assert response.status == 403
    assert body(response)["error"]["code"] == "missing_tenant_identity"


def test_post_run_rejects_foreign_document_reference():
    application = app()
    application.documents = (
        {"id": "d1", "tenant_id": "tenant-b", "organization_id": "org-b"},
    )
    principal = Principal(
        "user-1",
        frozenset({"runs:write"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request(
            "POST",
            "/v2/runs",
            headers={"Authorization": "Bearer ok"},
            body={"id": "r1", "document_id": "d1"},
        )
    )

    assert response.status == 404
    assert application.run_store.get("r1") is None
    assert application.queue.calls == []


def test_post_run_does_not_overwrite_foreign_tenant_run_id():
    application = app()
    foreign = Run(
        "shared",
        payload={"tenant_id": "tenant-b", "organization_id": "org-b"},
    )
    application.run_store.put(foreign)
    principal = Principal(
        "user-1",
        frozenset({"runs:write"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request(
            "POST",
            "/v2/runs",
            headers={"Authorization": "Bearer ok"},
            body={"id": "shared"},
        )
    )

    assert response.status == 409
    assert body(response)["error"]["code"] == "run_id_conflict"
    assert application.run_store.get("shared") is foreign
    assert application.queue.calls == []


def test_endpoints_return_resources_and_cancel():
    application = app()
    application.run_store.put(Run("r1", payload={"document_id": "d1"}))
    assert body(application.dispatch(Request("GET", "/v2/runs/r1")))["id"] == "r1"
    assert body(application.dispatch(Request("GET", "/v2/runs/r1/passport")))["entries"] == [{"ok": True}]
    assert body(application.dispatch(Request("GET", "/v2/runs/r1/artifacts")))["items"][0]["id"] == "a1"
    assert body(application.dispatch(Request("GET", "/v2/findings?run_id=r1")))["items"][0]["run_id"] == "r1"
    assert body(application.dispatch(Request("GET", "/v2/graph")))["nodes"] == ["r1", "a1"]
    assert application.dispatch(Request("POST", "/v2/runs/r1/cancel")).status == 200
    assert application.run_store.get("r1").status == "cancelled"


def test_authenticated_global_findings_only_return_owned_run_findings():
    application = app()
    application.run_store.put(
        Run("owned", payload={"tenant_id": "tenant-a", "organization_id": "org-a"})
    )
    application.run_store.put(
        Run("foreign", payload={"tenant_id": "tenant-b", "organization_id": "org-b"})
    )
    application.findings = (
        {"id": "owned-finding", "run_id": "owned"},
        {"id": "foreign-finding", "run_id": "foreign"},
        {"id": "unowned-finding"},
    )
    principal = Principal(
        "user-1",
        frozenset({"findings:read"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request("GET", "/v2/findings", headers={"Authorization": "Bearer ok"})
    )

    assert response.status == 200
    assert [item["id"] for item in body(response)["items"]] == ["owned-finding"]


def test_authenticated_global_findings_only_return_owned_document_findings():
    application = app()
    application.documents = (
        {"id": "owned", "tenant_id": "tenant-a", "organization_id": "org-a"},
        {"id": "foreign", "tenant_id": "tenant-b", "organization_id": "org-b"},
    )
    application.findings = (
        {"id": "owned-finding", "document_id": "owned"},
        {"id": "foreign-finding", "document_id": "foreign"},
    )
    principal = Principal(
        "user-1",
        frozenset({"findings:read"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request("GET", "/v2/findings", headers={"Authorization": "Bearer ok"})
    )

    assert response.status == 200
    assert [item["id"] for item in body(response)["items"]] == ["owned-finding"]


def test_authenticated_global_graph_fails_closed_when_graph_is_not_tenant_scoped():
    application = app()
    principal = Principal(
        "user-1",
        frozenset({"graph:read"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"})
    )

    assert response.status == 404
    assert body(response)["error"]["code"] == "not_found"


def test_wsgi_reaches_dynamic_endpoint():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/v2/runs/r1",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    captured = {}
    result = application(environ, lambda status, headers: captured.update(status=status, headers=headers))
    assert captured["status"].startswith("200")
    assert body(type("R", (), {"body": result[0]})())["id"] == "r1"


def test_dynamic_requests_use_auth_and_unknown_ids_are_not_found():
    application = app()
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None
    denied = application.dispatch(Request("GET", "/v2/runs/missing"))
    assert denied.status == 401
    found = application.dispatch(Request("GET", "/v2/runs/missing", headers={"Authorization": "Bearer ok"}))
    assert found.status == 404


def test_authenticated_run_access_hides_foreign_tenant_resource():
    application = app()
    application.run_store.put(
        Run(
            "r1",
            payload={
                "tenant_id": "tenant-b",
                "organization_id": "org-b",
                "owner_subject": "user-2",
            },
        )
    )
    principal = Principal(
        "user-1",
        frozenset({"runs:read"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request("GET", "/v2/runs/r1", headers={"Authorization": "Bearer ok"})
    )

    assert response.status == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v2/runs/r1/cancel"),
        ("GET", "/v2/runs/r1/passport"),
        ("GET", "/v2/runs/r1/artifacts"),
        ("GET", "/v2/runs/r1/progress"),
        ("GET", "/v2/runs/r1/findings"),
        ("GET", "/v2/runs/r1/graph"),
        ("GET", "/v2/runs/r1/previews/a1"),
    ],
)
def test_authenticated_run_subresources_hide_foreign_tenant_run(method, path):
    class PreviewArtifacts(Artifacts):
        def get(self, key):
            return Artifact(key, "r1", "image/png", "sha")

    application = app()
    application.artifact_store = PreviewArtifacts()
    application.run_store.put(
        Run("r1", payload={"tenant_id": "tenant-b", "organization_id": "org-b"})
    )
    assert application.dispatch(Request(method, path, body={} if method == "POST" else None)).status != 404
    principal = Principal(
        "user-1",
        ALL_SCOPES,
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request(
            method,
            path,
            headers={"Authorization": "Bearer ok"},
            body={} if method == "POST" else None,
        )
    )

    assert response.status == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v2/documents/d1"),
        ("GET", "/v2/documents/d1/runs"),
        ("POST", "/v2/documents/d1/revisions"),
    ],
)
def test_authenticated_document_resources_hide_foreign_tenant_document(method, path):
    application = app()
    application.documents = (
        {"id": "d1", "tenant_id": "tenant-b", "organization_id": "org-b"},
    )
    assert application.dispatch(Request(method, path, body={} if method == "POST" else None)).status != 404
    principal = Principal(
        "user-1",
        ALL_SCOPES,
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request(
            method,
            path,
            headers={"Authorization": "Bearer ok"},
            body={} if method == "POST" else None,
        )
    )

    assert response.status == 404


def test_authenticated_document_runs_only_return_owned_runs():
    class ListedRuns(Runs):
        def list_for_document(self, document_id):
            return list(self.items.values())

    application = app()
    application.run_store = ListedRuns()
    application.documents = (
        {"id": "d1", "tenant_id": "tenant-a", "organization_id": "org-a"},
    )
    application.run_store.put(
        Run("owned", payload={"document_id": "d1", "tenant_id": "tenant-a", "organization_id": "org-a"})
    )
    application.run_store.put(
        Run("foreign", payload={"document_id": "d1", "tenant_id": "tenant-b", "organization_id": "org-b"})
    )
    principal = Principal(
        "user-1",
        frozenset({"documents:read"}),
        tenant_id="tenant-a",
        organization_id="org-a",
    )
    application.auth = lambda token: principal if token == "ok" else None

    response = application.dispatch(
        Request("GET", "/v2/documents/d1/runs", headers={"Authorization": "Bearer ok"})
    )

    assert [item["id"] for item in body(response)["items"]] == ["owned"]


def test_dynamic_auth_validator_is_resolved_at_request_time():
    application = app()
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None
    assert application.dispatch(Request("GET", "/v2/runs/r1", headers={"Authorization": "Bearer ok"})).status == 404
    application.auth = lambda token: Principal("grace", ALL_SCOPES) if token == "new" else None
    assert application.dispatch(Request("GET", "/v2/runs/r1", headers={"Authorization": "Bearer new"})).status == 404


def test_dynamic_registration_and_auth_refresh_are_thread_safe():
    class MutationDetectingRouter(Router):
        def __setattr__(self, name, value):
            if name == "_routes" and hasattr(self, "_routes"):
                raise AssertionError("routes must not be replaced during a live request")
            super().__setattr__(name, value)

    application = app(router=MutationDetectingRouter())
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None
    barrier = threading.Barrier(3)
    statuses = []
    failures = []

    def register_dynamic_route():
        try:
            barrier.wait()
            response = application.dispatch(Request("GET", "/v2/runs/r1", headers={"Authorization": "Bearer ok"}))
            statuses.append(response.status)
        except Exception as exc:  # pragma: no cover - failures are asserted below
            failures.append(exc)

    def refresh_authentication():
        try:
            barrier.wait()
            response = application.dispatch(Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"}))
            statuses.append(response.status)
        except Exception as exc:  # pragma: no cover - failures are asserted below
            failures.append(exc)

    dynamic = threading.Thread(target=register_dynamic_route)
    refresher = threading.Thread(target=refresh_authentication)
    for thread in [dynamic, refresher]:
        thread.start()
    barrier.wait()
    for thread in [dynamic, refresher]:
        thread.join()

    assert failures == []
    assert sorted(statuses) == [404, 404]


def test_static_endpoints_require_configured_authentication():
    application = app()
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None

    for method, path in (("GET", "/v2/graph"), ("GET", "/v2/documents"), ("GET", "/v2/findings"), ("POST", "/v2/runs")):
        assert application.dispatch(Request(method, path)).status == 401

    assert application.dispatch(Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"})).status == 404


def test_enabling_auth_after_dynamic_route_creation_requires_authentication():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    assert application.dispatch(Request("GET", "/v2/runs/r1")).status == 200

    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None
    assert application.dispatch(Request("GET", "/v2/runs/r1")).status == 401
    assert application.dispatch(Request("GET", "/v2/runs/r1", headers={"Authorization": "Bearer ok"})).status == 404


def test_passport_and_artifacts_return_404_for_unknown_run():
    application = app()
    assert application.dispatch(Request("GET", "/v2/runs/missing/passport")).status == 404
    assert application.dispatch(Request("GET", "/v2/runs/missing/artifacts")).status == 404


def test_cancel_is_terminal_idempotent_and_queue_aware():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    first = application.dispatch(Request("POST", "/v2/runs/r1/cancel"))
    second = application.dispatch(Request("POST", "/v2/runs/r1/cancel"))
    assert first.status == second.status == 200
    assert application.queue.cancel_calls == ["r1"]


def test_cancel_does_not_mutate_a_succeeded_run():
    application = app()
    application.run_store.put(Run("r1", status="succeeded", payload={}))

    response = application.dispatch(Request("POST", "/v2/runs/r1/cancel"))

    assert response.status == 200
    assert application.run_store.get("r1").status == "succeeded"
    assert application.queue.cancel_calls == []


def test_retry_assigns_the_new_run_id_to_the_worker_payload():
    application = app()
    application.run_store.put(Run("r1", status="failed", payload={"document_id": "d1"}))

    response = application.dispatch(Request("POST", "/v2/runs/r1/retry"))

    assert response.status == 201
    retry_id = body(response)["id"]
    assert retry_id != "r1"
    assert application.queue.calls[-1][0] == retry_id
    assert application.queue.calls[-1][1]["run_id"] == retry_id


def test_router_owns_idempotency_and_concurrent_replay():
    application = app()
    responses = []

    def create():
        responses.append(
            application.dispatch(Request("POST", "/v2/runs", body={"id": "r1"}, headers={"Idempotency-Key": "k"}))
        )

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status for response in responses] == [201, 201]
    assert len(application.queue.calls) == 1
    distinct_request = application.dispatch(Request("POST", "/v2/runs", body={"id": "r2"}, headers={"Idempotency-Key": "k"}))
    assert distinct_request.status == 201


def test_concurrent_cancellation_is_atomic_and_cancels_once():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    responses = []
    threads = [threading.Thread(target=lambda: responses.append(application.dispatch(Request("POST", "/v2/runs/r1/cancel")))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status for response in responses] == [200, 200]
    assert application.queue.cancel_calls == ["r1"]


def test_router_rate_limit_returns_retry_metadata():
    router = Router(
        rate_limiter=TokenBucketRateLimiter(rate=1, capacity=1),
        rate_limit_key=lambda request: request.headers.get("X-Tenant", "anonymous"),
    )
    router.route("GET", "/limited")(lambda request: Response.json({"ok": True}))

    assert router.dispatch(Request("GET", "/limited", {"X-Tenant": "tenant-1"})).status == 200
    response = router.dispatch(Request("GET", "/limited", {"X-Tenant": "tenant-1"}))

    assert response.status == 429
    assert response.headers["retry-after"]
    assert body(response)["error"]["code"] == "rate_limited"
    assert body(response)["error"]["details"]["remaining"] == 0


def test_router_enforces_optional_oidc_scope_policy():
    router = Router()
    router.route(
        "GET",
        "/scoped",
        auth=lambda token: Principal("ada", frozenset({"documents:read"})) if token == "ok" else None,
        scopes=scope_policy(all_of=("documents:write",)),
    )(lambda request: Response.json({"ok": True}))

    response = router.dispatch(Request("GET", "/scoped", {"Authorization": "Bearer ok"}))

    assert response.status == 403
    assert body(response)["error"]["code"] == "insufficient_scope"


def test_application_propagates_authenticated_principal_to_handlers():
    application = app()
    principal = Principal("ada", frozenset({"graph:read"}))
    application.auth = lambda token: principal if token == "ok" else None
    seen = {}
    guarded = application._authenticated(
        lambda request: (seen.update(principal=request.principal) or Response.json({"ok": True}))
    )

    response = guarded(Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"}))

    assert response.status == 200
    assert seen["principal"] == principal


def test_application_denies_missing_scope_with_bearer_challenge():
    application = app()
    application.auth = lambda token: Principal("ada", frozenset({"documents:read"})) if token == "ok" else None

    response = application.dispatch(Request("GET", "/v2/graph", headers={"Authorization": "Bearer ok"}))

    assert response.status == 403
    assert body(response)["error"]["code"] == "insufficient_scope"
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api", error="insufficient_scope", scope="graph:read"'


def test_application_bearer_challenge_is_returned_for_missing_credentials():
    application = app()
    application.auth = lambda token: Principal("ada", ALL_SCOPES) if token == "ok" else None

    response = application.dispatch(Request("GET", "/v2/graph"))

    assert response.status == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="api"'


@pytest.mark.parametrize(
    ("method", "path", "scope"),
    [
        ("GET", "/v2/graph", "graph:read"),
        ("GET", "/v2/documents", "documents:read"),
        ("GET", "/v2/documents/d1", "documents:read"),
        ("GET", "/v2/documents/d1/runs", "documents:read"),
        ("PATCH", "/v2/workspaces/w1", "workspaces:write"),
        ("POST", "/v2/documents/d1/revisions", "documents:write"),
        ("GET", "/v2/findings", "findings:read"),
        ("GET", "/v2/runs/r1", "runs:read"),
        ("POST", "/v2/runs", "runs:write"),
        ("POST", "/v2/runs/r1/cancel", "runs:write"),
        ("GET", "/v2/runs/r1/progress", "runs:read"),
        ("GET", "/v2/runs/r1/findings", "findings:read"),
        ("GET", "/v2/runs/r1/graph", "graph:read"),
        ("GET", "/v2/runs/r1/passport", "passport:read"),
        ("GET", "/v2/runs/r1/artifacts", "artifacts:read"),
        ("GET", "/v2/runs/r1/previews/a1", "artifacts:read"),
        ("GET", "/v2/baselines", "baselines:read"),
        ("GET", "/v2/plugins", "plugins:read"),
    ],
)
def test_application_scope_policy_covers_owned_routes(method, path, scope):
    assert X20Application._required_scope(method, path) == scope


def test_application_scope_policy_does_not_overmatch_dynamic_routes():
    assert X20Application._required_scope("GET", "/v2/runs/r1/unknown") is None
    assert X20Application._required_scope("GET", "/v2/documents/d1/revisions") is None
    assert X20Application._required_scope("GET", "/v2/openapi.json") is None
    assert app().dispatch(Request("GET", "/v2/runs//passport")).status == 404


def test_run_progress_is_exposed_as_sse():
    application = app()
    application.run_store.put(
        Run(
            "r1",
            "running",
            {
                "document_id": "d1",
                "progress": {"stage": "verify", "percent": 75},
            },
            "2026-01-01T00:00:00+00:00",
        )
    )

    response = application.dispatch(Request("GET", "/v2/runs/r1/progress"))

    assert response.status == 200
    assert response.headers["content-type"] == "text/event-stream"
    assert response.body.startswith(b"id: r1\nevent: progress\n")
    assert b'"id":"r1"' in response.body
    assert b'"type":"verify"' in response.body
    assert b'"progress":75' in response.body
    assert b'"message":"verify: 75%"' in response.body


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v2/documents/d1"),
        ("GET", "/v2/documents/d1/runs"),
        ("GET", "/v2/runs/r1/findings"),
        ("GET", "/v2/runs/r1/graph"),
        ("GET", "/v2/runs/r1/previews/a1"),
        ("POST", "/v2/documents/d1/revisions"),
        ("GET", "/v2/baselines"),
        ("GET", "/v2/plugins"),
    ],
)
def test_x20_resource_routes_exist(method, path):
    application = app()
    if path.startswith("/v2/runs/"):
        application.run_store.put(Run("r1", payload={"document_id": "d1"}))
    application.dispatch(Request(method, path, body={} if method == "POST" else None))
    assert (method, path) in application._dynamic_routes or (method, path) in application._registered_route_keys()


def test_x20_resource_routes_are_safe_for_missing_resources():
    application = app()

    assert application.dispatch(Request("GET", "/v2/documents/missing")).status == 404
    assert application.dispatch(Request("GET", "/v2/documents/missing/runs")).status == 404
    assert application.dispatch(Request("GET", "/v2/runs/missing/findings")).status == 404
    assert application.dispatch(Request("GET", "/v2/runs/missing/previews/missing.png")).status == 404
    assert application.dispatch(Request("POST", "/v2/documents/missing/revisions", body={})).status == 404
    assert body(application.dispatch(Request("GET", "/v2/baselines"))) == {"items": [], "next_cursor": None}
    assert application.dispatch(Request("POST", "/v2/baselines/promotions", body={})).status == 404
    assert body(application.dispatch(Request("GET", "/v2/plugins"))) == {"items": [], "next_cursor": None}


class Baselines:
    def __init__(self):
        self.promotions = []

    def list(self):
        return [{"id": "base-1", "status": "passed"}, {"id": "base-2", "status": "warnings"}]

    def promote(self, baseline_id, payload):
        self.promotions.append((baseline_id, payload))
        return {"id": baseline_id, "status": "passed", "promoted": True}


def test_promote_baseline_uses_non_workspace_callback_when_workspace_callback_is_not_callable(tmp_path):
    class FallbackBaselines:
        promote_for_workspace = None

        def __init__(self):
            self.calls = []

        def promote(self, baseline_id, payload):
            self.calls.append((baseline_id, payload))
            return {"id": baseline_id, "promoted": True}

    registry = WorkspaceRegistry(tmp_path / "registry.json")
    workspace = registry.create("Workspace", tmp_path / "workspace")
    baselines = FallbackBaselines()
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), baseline_store=baselines, workspace_registry=registry,
    )

    response = application._promote_baseline(
        Request("POST", "/v2/baselines/promotions", body={"baseline_id": "base-1", "workspace_id": workspace["id"]})
    )

    assert body(response) == {"id": "base-1", "promoted": True}
    assert baselines.calls == [("base-1", {"baseline_id": "base-1", "workspace_id": workspace["id"]})]


class Plugins:
    def list(self):
        return [{"id": "plugin-b", "version": "2"}, {"id": "plugin-a", "version": "1"}]


def test_baselines_and_plugins_use_existing_read_store_contracts():
    baselines = Baselines()
    application = X20Application(
        run_store=Runs(),
        queue=Queue(),
        passport_store=Passports(),
        artifact_store=Artifacts(),
        graph_store=Graphs(),
        baseline_store=baselines,
        plugin_store=Plugins(),
    )

    baseline_page = application.dispatch(Request("GET", "/v2/baselines?limit=1"))
    plugin_page = application.dispatch(Request("GET", "/v2/plugins?limit=1"))
    plugin_detail = application.dispatch(Request("GET", "/v2/plugins/plugin-a"))

    assert body(baseline_page)["items"] == [{"id": "base-1", "status": "passed"}]
    assert body(baseline_page)["next_cursor"]
    assert body(plugin_page)["items"] == [{"id": "plugin-b", "version": "2"}]
    assert body(plugin_page)["next_cursor"]
    assert body(plugin_detail) == {"id": "plugin-a", "version": "1"}
    assert application.dispatch(Request("POST", "/v2/baselines/promotions", body={})).status == 404


class SemanticGraphs:
    def get(self):
        return SemanticGraph(
            nodes=(
                SemanticNode("claim-supported", "claim", "Supported claim"),
                SemanticNode("claim-missing", "claim", "Missing claim"),
                SemanticNode("evidence-1", "evidence", "Evidence"),
                SemanticNode("revision-1", "revision", "Revision"),
                SemanticNode("finding-1", "finding", "Finding"),
                SemanticNode("input-1", "input", "Input"),
                SemanticNode("artifact-1", "artifact", "Artifact"),
                SemanticNode("reference-used", "reference", "Used reference"),
                SemanticNode("reference-unused", "reference", "Unused reference"),
                SemanticNode("requirement-met", "requirement", "Met requirement"),
                SemanticNode("requirement-unmet", "requirement", "Unmet requirement"),
                SemanticNode("consumer-1", "consumer", "Consumer"),
            ),
            edges=(
                SemanticEdge("evidence-1", "claim-supported", "supports"),
                SemanticEdge("revision-1", "finding-1", "affects"),
                SemanticEdge("artifact-1", "input-1", "derived_from"),
                SemanticEdge("consumer-1", "reference-used", "references"),
                SemanticEdge("consumer-1", "requirement-met", "satisfies"),
            ),
        )


def semantic_app():
    return X20Application(
        run_store=Runs(),
        queue=Queue(),
        passport_store=Passports(),
        artifact_store=Artifacts(),
        graph_store=SemanticGraphs(),
    )


@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        ("mode=claims_without_evidence", ["claim-missing"]),
        ("mode=findings_affected_by_revision&revision_id=revision-1", ["finding-1"]),
        ("mode=artifacts_derived_from_input&input_id=input-1", ["artifact-1"]),
        ("mode=unused_references", ["reference-unused"]),
        ("mode=unmet_requirements", ["requirement-unmet"]),
    ],
)
def test_graph_query_modes_expose_domain_read_models(query, expected_ids):
    response = semantic_app().dispatch(Request("GET", f"/v2/graph?{query}"))

    assert response.status == 200
    assert [item["id"] for item in body(response)["items"]] == expected_ids


def test_graph_query_mode_requires_its_identifier():
    response = semantic_app().dispatch(Request("GET", "/v2/graph?mode=findings_affected_by_revision"))

    assert response.status == 400
    assert body(response)["error"]["code"] == "invalid_graph_query"


@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        ("claims_without_evidence", ["claim-missing"]),
        ("findings_affected_by_revision&id=revision-1", ["finding-1"]),
        ("artifacts_derived_from_input&id=input-1", ["artifact-1"]),
        ("unused_references", ["reference-unused"]),
        ("unmet_requirements", ["requirement-unmet"]),
    ],
)
def test_graph_query_aliases_expose_review_studio_contract(query, expected_ids):
    response = semantic_app().dispatch(Request("GET", f"/v2/graph?query={query}"))

    assert response.status == 200
    assert [item["id"] for item in body(response)["items"]] == expected_ids


def test_run_graph_preserves_graph_query_aliases():
    application = semantic_app()
    application.run_store.put(Run("r1", payload={}))

    response = application.dispatch(
        Request("GET", "/v2/runs/r1/graph?query=findings_affected_by_revision&id=revision-1")
    )

    assert response.status == 200
    assert [item["id"] for item in body(response)["items"]] == ["finding-1"]


def test_run_graph_requires_an_existing_run():
    response = semantic_app().dispatch(Request("GET", "/v2/runs/missing/graph"))

    assert response.status == 404
    assert body(response)["error"]["code"] == "not_found"


@pytest.mark.parametrize("query", ["findings_affected_by_revision", "artifacts_derived_from_input"])
def test_graph_query_alias_requires_id(query):
    response = semantic_app().dispatch(Request("GET", f"/v2/graph?query={query}"))

    assert response.status == 400
    assert body(response)["error"]["code"] == "invalid_graph_query"


def test_graph_query_rejects_conflicting_query_and_mode():
    response = semantic_app().dispatch(
        Request("GET", "/v2/graph?query=unused_references&mode=unused_references")
    )

    assert response.status == 400
    assert body(response)["error"] == {
        "code": "invalid_graph_query",
        "message": "query and mode cannot be used together",
        "details": {},
    }
