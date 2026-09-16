import io
import json
import threading

import pytest

from docs.api.application import X20Application
from docs.api.auth import Principal
from docs.api.http import Request, Response, Router
from docs.domain.contracts import Artifact, Graph, Passport, Run


class Runs:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.id] = item

    def get(self, key):
        return self.items.get(key)


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
    def list_for_run(self, key):
        return [Artifact("a1", key, "docx", "sha")]

    def get(self, key):
        return None


class Graphs:
    def get(self):
        return Graph(("r1", "a1"), (("r1", "a1"),))


def body(response):
    return json.loads(response.body)


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
    router.route("GET", "/v1/runs/r1")(lambda _: Response.json({"owner": "other"}))

    with pytest.raises(ValueError, match="GET /v1/runs/r1"):
        X20Application(
            run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
            graph_store=Graphs(), router=router,
        )


def test_auth_refresh_preserves_unrelated_router_routes():
    router = Router()

    def unrelated(_):
        return Response.json({"owner": "other"})

    router.route("GET", "/v1/other")(unrelated)
    application = X20Application(
        run_store=Runs(), queue=Queue(), passport_store=Passports(), artifact_store=Artifacts(),
        graph_store=Graphs(), router=router,
    )
    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None
    application.dispatch(Request("GET", "/v1/graph", headers={"Authorization": "Bearer ok"}))

    assert body(router.dispatch(Request("GET", "/v1/other"))) == {"owner": "other"}


def test_post_run_is_idempotent_and_enqueues_once():
    application = app()
    request = Request("POST", "/v1/runs", body={"id": "r1", "document_id": "d1"}, headers={"Idempotency-Key": "same"})
    first = application.dispatch(request)
    second = application.dispatch(request)
    assert first.status == second.status == 201
    assert body(first)["id"] == body(second)["id"] == "r1"
    assert len(application.queue.calls) == 1


def test_endpoints_return_resources_and_cancel():
    application = app()
    application.run_store.put(Run("r1", payload={"document_id": "d1"}))
    assert body(application.dispatch(Request("GET", "/v1/runs/r1")))["id"] == "r1"
    assert body(application.dispatch(Request("GET", "/v1/runs/r1/passport")))["entries"] == [{"ok": True}]
    assert body(application.dispatch(Request("GET", "/v1/runs/r1/artifacts")))["items"][0]["id"] == "a1"
    assert body(application.dispatch(Request("GET", "/v1/findings?run_id=r1")))["items"][0]["run_id"] == "r1"
    assert body(application.dispatch(Request("GET", "/v1/graph")))["nodes"] == ["r1", "a1"]
    assert application.dispatch(Request("POST", "/v1/runs/r1/cancel")).status == 200
    assert application.run_store.get("r1").status == "cancelled"


def test_documents_are_filtered_and_paginated():
    application = app()
    response = application.dispatch(Request("GET", "/v1/documents?owner=ada&limit=1"))
    assert body(response) == {"items": [{"id": "d1", "owner": "ada"}], "next_cursor": None}


def test_wsgi_reaches_dynamic_endpoint():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/v1/runs/r1",
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    captured = {}
    result = application(environ, lambda status, headers: captured.update(status=status, headers=headers))
    assert captured["status"].startswith("200")
    assert body(type("R", (), {"body": result[0]})())["id"] == "r1"


def test_dynamic_requests_use_auth_and_unknown_ids_are_not_found():
    application = app()
    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None
    denied = application.dispatch(Request("GET", "/v1/runs/missing"))
    assert denied.status == 401
    found = application.dispatch(Request("GET", "/v1/runs/missing", headers={"Authorization": "Bearer ok"}))
    assert found.status == 404


def test_dynamic_auth_validator_is_resolved_at_request_time():
    application = app()
    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None
    assert application.dispatch(Request("GET", "/v1/runs/r1", headers={"Authorization": "Bearer ok"})).status == 404
    application.auth = lambda token: Principal("grace", frozenset()) if token == "new" else None
    assert application.dispatch(Request("GET", "/v1/runs/r1", headers={"Authorization": "Bearer new"})).status == 404


def test_dynamic_registration_and_auth_refresh_are_thread_safe():
    class MutationDetectingRouter(Router):
        def __setattr__(self, name, value):
            if name == "_routes" and hasattr(self, "_routes"):
                raise AssertionError("routes must not be replaced during a live request")
            super().__setattr__(name, value)

    application = app(router=MutationDetectingRouter())
    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None
    barrier = threading.Barrier(3)
    statuses = []
    failures = []

    def register_dynamic_route():
        try:
            barrier.wait()
            response = application.dispatch(Request("GET", "/v1/runs/r1", headers={"Authorization": "Bearer ok"}))
            statuses.append(response.status)
        except Exception as exc:  # pragma: no cover - failures are asserted below
            failures.append(exc)

    def refresh_authentication():
        try:
            barrier.wait()
            response = application.dispatch(Request("GET", "/v1/graph", headers={"Authorization": "Bearer ok"}))
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
    assert sorted(statuses) == [200, 404]


def test_static_endpoints_require_configured_authentication():
    application = app()
    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None

    for method, path in (("GET", "/v1/graph"), ("GET", "/v1/documents"), ("GET", "/v1/findings"), ("POST", "/v1/runs")):
        assert application.dispatch(Request(method, path)).status == 401

    assert application.dispatch(Request("GET", "/v1/graph", headers={"Authorization": "Bearer ok"})).status == 200


def test_enabling_auth_after_dynamic_route_creation_requires_authentication():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    assert application.dispatch(Request("GET", "/v1/runs/r1")).status == 200

    application.auth = lambda token: Principal("ada", frozenset()) if token == "ok" else None
    assert application.dispatch(Request("GET", "/v1/runs/r1")).status == 401
    assert application.dispatch(Request("GET", "/v1/runs/r1", headers={"Authorization": "Bearer ok"})).status == 200


def test_passport_and_artifacts_return_404_for_unknown_run():
    application = app()
    assert application.dispatch(Request("GET", "/v1/runs/missing/passport")).status == 404
    assert application.dispatch(Request("GET", "/v1/runs/missing/artifacts")).status == 404


def test_invalid_limit_is_api_error():
    response = app().dispatch(Request("GET", "/v1/documents?limit=nope"))
    assert response.status == 400
    assert body(response)["error"]["code"] == "invalid_pagination"


def test_cancel_is_terminal_idempotent_and_queue_aware():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    first = application.dispatch(Request("POST", "/v1/runs/r1/cancel"))
    second = application.dispatch(Request("POST", "/v1/runs/r1/cancel"))
    assert first.status == second.status == 200
    assert application.queue.cancel_calls == ["r1"]


def test_router_owns_idempotency_and_concurrent_replay():
    application = app()
    responses = []

    def create():
        responses.append(
            application.dispatch(Request("POST", "/v1/runs", body={"id": "r1"}, headers={"Idempotency-Key": "k"}))
        )

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status for response in responses] == [201, 201]
    assert len(application.queue.calls) == 1
    distinct_request = application.dispatch(Request("POST", "/v1/runs", body={"id": "r2"}, headers={"Idempotency-Key": "k"}))
    assert distinct_request.status == 201


def test_concurrent_cancellation_is_atomic_and_cancels_once():
    application = app()
    application.run_store.put(Run("r1", payload={}))
    responses = []
    threads = [threading.Thread(target=lambda: responses.append(application.dispatch(Request("POST", "/v1/runs/r1/cancel")))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status for response in responses] == [200, 200]
    assert application.queue.cancel_calls == ["r1"]
