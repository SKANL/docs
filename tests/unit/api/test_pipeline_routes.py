"""Pipeline plan, durable run creation, run list filters and the SSE watch stream."""

import io
import json

import pytest

from docs.api.auth import Principal
from docs.api.openapi import build_capability_catalog, build_openapi_document
from docs.api.server import ApiTransport, TransportConfig
from docs.domain.runtime_records import Run

NEW_COMMANDS = {
    "document plan": ("POST", "/v2/documents/{document_id}/plan", "documents:read"),
    "document run": ("POST", "/v2/documents/{document_id}/run", "documents:write"),
    "document release": ("POST", "/v2/documents/{document_id}/run", "documents:write"),
    "run watch": ("GET", "/v2/runs/{run_id}/progress", "runs:read"),
}


class MemRuns:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.id] = item

    def get(self, key):
        return self.items.get(key)

    def list(self):
        return list(self.items.values())


class RecordingQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job_id, payload):
        self.jobs.append((job_id, dict(payload)))


@pytest.fixture
def stores(stores):
    return {**stores, "run_store": MemRuns(), "queue": RecordingQueue()}


def body(response):
    return json.loads(response.body)


def put_run(api, run_id, status="queued", **payload):
    run = Run(run_id, status, {"workspace_id": api.wid, **payload}, "2026-01-01T00:00:00+00:00")
    api.app.run_store.put(run)
    return run


# -- plan ---------------------------------------------------------------------
def test_plan_returns_the_resolved_pipeline_the_cli_prints(api):
    response = api("POST", "/v2/documents/doc/plan", {})
    assert response.status == 200, response.body
    data = body(response)
    assert data["document_id"] == "doc" and data["pipeline_id"] == "document"
    assert data["stages"] and all(isinstance(stage, str) for stage in data["stages"])
    assert "contracts" in data and "external_artifacts" in data


def test_plan_unknown_pipeline_is_400_and_missing_document_is_404(api):
    bad = api("POST", "/v2/documents/doc/plan", {"pipeline_id": "nope"})
    assert bad.status == 400 and body(bad)["error"]["code"] == "unknown_pipeline"
    assert api("POST", "/v2/documents/ghost/plan", {}).status == 404
    assert api("POST", "/v2/documents/doc/plan", {"format": "rtf"}).status == 400


# -- run creation ---------------------------------------------------------------
def test_run_enqueues_and_returns_a_run_reference(api):
    response = api("POST", "/v2/documents/doc/run", {"format": "pdf", "strict": True})
    assert response.status == 202, response.body
    data = body(response)
    assert data["status"] == "queued" and data["format"] == "pdf" and data["policy"] == "strict"
    assert data["links"] == {
        "self": f"/v2/runs/{data['id']}",
        "progress": f"/v2/runs/{data['id']}/progress",
        "cancel": f"/v2/runs/{data['id']}/cancel",
    }
    job_id, payload = api.app.queue.jobs[0]
    assert job_id == data["id"] == payload["run_id"]
    assert payload["document_id"] == "doc" and payload["pipeline_id"] == "document"
    assert payload["workspace_id"] == api.wid
    assert api.app.run_store.get(data["id"]).status == "queued"


def test_run_defaults_match_the_cli(api):
    data = body(api("POST", "/v2/documents/doc/run", {}))
    assert data["format"] == "docx" and data["policy"] == "release"
    explicit = body(api("POST", "/v2/documents/doc/run", {"release": True, "policy": "draft"}))
    assert explicit["policy"] == "draft"  # --policy wins, as in `document run`


@pytest.mark.parametrize(
    "payload",
    [{"strict": True, "release": True}, {"format": "rtf"}, {"policy": "bogus"}, {"pipeline_id": "nope"}],
)
def test_invalid_run_requests_enqueue_nothing(api, payload):
    assert api("POST", "/v2/documents/doc/run", payload).status == 400
    assert api.app.queue.jobs == []


def test_run_without_a_workspace_is_rejected_so_no_null_workspace_is_queued(api):
    # H1 item 2: the only wiring resolves a workspace from query/body or fails
    # closed, so a queued payload can never carry workspace_id=None.
    from docs.api.http import Request

    response = api.app.dispatch(Request("POST", "/v2/documents/doc/run", body={}))
    assert response.status == 400 and body(response)["error"]["code"] == "workspace_required"
    assert api.app.queue.jobs == []


def test_run_for_a_missing_document_is_404(api):
    assert api("POST", "/v2/documents/ghost/run", {}).status == 404
    assert api.app.queue.jobs == []


def test_run_stamps_the_owner_so_the_caller_can_watch_it(api):
    owner = Principal("ada", frozenset({"documents:write", "runs:read"}), "t1", "o1")
    api.app.auth = lambda token: owner if token == "ok" else None
    headers = {"Authorization": "Bearer ok"}
    created = body(api("POST", "/v2/documents/doc/run", {}, headers=headers))
    _, payload = api.app.queue.jobs[0]
    assert payload["tenant_id"] == "t1" and payload["owner_subject"] == "ada"
    assert api("GET", f"/v2/runs/{created['id']}", headers=headers).status == 200


# -- scopes, openapi, catalogue ---------------------------------------------------
def test_pipeline_routes_enforce_scopes(api):
    reader = Principal("ada", frozenset({"documents:read"}))
    api.app.auth = lambda token: reader if token == "ok" else None
    headers = {"Authorization": "Bearer ok"}
    assert api("POST", "/v2/documents/doc/plan", {}, headers=headers).status == 200
    denied = api("POST", "/v2/documents/doc/run", {}, headers=headers)
    assert denied.status == 403 and body(denied)["error"]["code"] == "insufficient_scope"
    put_run(api, "r1")
    assert api("GET", "/v2/runs/r1/progress", headers=headers).status == 403


def test_openapi_and_catalogue_declare_every_pipeline_command():
    paths = build_openapi_document()["paths"]
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, path, scope) in NEW_COMMANDS.items():
        assert paths[path][method.lower()]["x-rbac-scopes"] == [scope], command
        assert catalogue[command]["status"] == "available", command
        assert catalogue[command]["route"] == f"{method} {path}", command
    run = paths["/v2/documents/{document_id}/run"]["post"]
    assert "202" in run["responses"] and "always asynchronous" in run["summary"]


# -- run list filters + cursor ------------------------------------------------------
def test_run_list_filters_by_status_and_document_and_pages_with_a_cursor(api):
    for index in range(5):
        put_run(api, f"a{index}", "failed" if index % 2 else "queued", document_id="doc")
    put_run(api, "b0", "failed", document_id="other")
    failed = body(api("GET", "/v2/runs?status=failed"))
    assert {item["id"] for item in failed["items"]} == {"a1", "a3", "b0"}
    scoped = body(api("GET", "/v2/runs?status=failed&document_id=doc"))
    assert {item["id"] for item in scoped["items"]} == {"a1", "a3"}
    first = body(api("GET", "/v2/runs?document_id=doc&limit=2"))
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = body(api("GET", f"/v2/runs?document_id=doc&limit=2&cursor={first['next_cursor']}"))
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(seen)) == 4 and all(i.startswith("a") for i in seen)


# -- watch (SSE) ---------------------------------------------------------------------
def kind(chunk):
    text = chunk.decode()
    return text.split("event: ", 1)[1].split("\n", 1)[0] if "event: " in text else "comment"


def test_progress_streams_changes_then_terminal_event_and_closes(api):
    api.app.progress_poll_interval = 0.0
    put_run(api, "r1", document_id="doc")
    response = api("GET", "/v2/runs/r1/progress")
    assert response.status == 200 and response.headers["content-type"] == "text/event-stream"
    stream = iter(response.stream)
    first = next(stream)
    assert kind(first) == "progress" and b'"status":"queued"' in first
    put_run(api, "r1", "running", document_id="doc", progress={"stage": "verify", "percent": 75})
    second = next(stream)
    assert kind(second) == "progress" and b'"progress":75' in second
    put_run(api, "r1", "succeeded", document_id="doc", progress={"stage": "finalize", "percent": 100})
    assert kind(next(stream)) == "progress"
    last = next(stream)
    assert kind(last) == "terminal" and b'"status":"succeeded"' in last
    with pytest.raises(StopIteration):
        next(stream)


def test_progress_is_bounded_and_sends_heartbeats(api):
    api.app.progress_poll_interval = 0.0
    api.app.progress_heartbeat_seconds = 0.0
    api.app.progress_max_seconds = 0.05
    put_run(api, "r1")
    chunks = list(api("GET", "/v2/runs/r1/progress").stream)  # ends by itself: it cannot hang a thread
    assert kind(chunks[0]) == "progress" and b": keepalive" in b"".join(chunks)


def test_progress_once_keeps_the_single_frame_contract(api):
    put_run(api, "r1")
    response = api("GET", "/v2/runs/r1/progress?once=1")
    assert response.stream is None and response.body.startswith(b"id: r1\nevent: progress\n")


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_progress_once_falsey_values_stream(api, value):
    put_run(api, "r1")
    response = api("GET", f"/v2/runs/r1/progress?once={value}")
    assert response.stream is not None


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_progress_once_truthy_values_return_one_frame(api, value):
    put_run(api, "r1")
    assert api("GET", f"/v2/runs/r1/progress?once={value}").stream is None


def test_run_payload_progress_cannot_change_in_place(api):
    # H1 item 3: change detection may keep the previous progress mapping
    # because Run freezes its payload, so in-place updates are impossible.
    run = put_run(api, "r1", progress={"stage": "a", "percent": 1})
    with pytest.raises(TypeError):
        run.payload["progress"]["percent"] = 2


def test_progress_of_a_foreign_run_is_rejected_before_any_frame(api):
    foreign = {"workspace_id": api.wid, "tenant_id": "t2", "organization_id": "o2"}
    api.app.run_store.put(Run("r1", "running", foreign, ""))
    api.app.auth = lambda token: Principal("ada", frozenset({"runs:read"}), "t1", "o1") if token == "ok" else None
    response = api("GET", "/v2/runs/r1/progress", headers={"Authorization": "Bearer ok"})
    assert response.status == 404 and response.stream is None and b"event:" not in response.body
    assert api("GET", "/v2/runs/ghost/progress", headers={"Authorization": "Bearer ok"}).status == 404


def test_progress_streams_through_the_wsgi_transport(api):
    api.app.progress_poll_interval = 0.0
    put_run(api, "r1", "failed")
    captured = {}
    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": "/v2/runs/r1/progress", "QUERY_STRING": f"workspace_id={api.wid}",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0",
    }

    def start_response(status, headers, exc_info=None):
        captured["status"], captured["headers"] = status, dict(headers)

    chunks = list(ApiTransport(api.app, TransportConfig())(environ, start_response))
    assert captured["status"].startswith("200") and captured["headers"]["Transfer-Encoding"] == "chunked"
    assert [kind(chunk) for chunk in chunks] == ["progress", "terminal"]


# -- cancel / retry still work on a run created here ----------------------------------
def test_created_runs_can_be_cancelled_and_retried(api):
    run_id = body(api("POST", "/v2/documents/doc/run", {}))["id"]
    cancelled = body(api("POST", f"/v2/runs/{run_id}/cancel"))
    assert cancelled["status"] == "cancelled"
    retried = api("POST", f"/v2/runs/{run_id}/retry")
    assert retried.status == 201 and body(retried)["payload"]["retry_of"] == run_id
    assert len(api.app.queue.jobs) == 2
