import json
import threading

import pytest

from docs.api.http import APIError, Request, Response, Router, decode_cursor, paginate
from docs.infrastructure.persistence.idempotency import SqliteIdempotencyStore


def test_router_dispatches_json_and_cors():
    router = Router()

    @router.route("GET", "/v1/health")
    def health(request: Request) -> Response:
        return Response.json({"status": "ok"})

    response = router.dispatch(Request("GET", "/v1/health"))
    assert response.status == 200
    assert json.loads(response.body) == {"status": "ok"}
    assert "access-control-allow-origin" not in response.headers


def test_router_allows_only_configured_cors_origin():
    router = Router(cors_origins=["https://example.test"])
    router.route("GET", "/v1/health")(lambda request: Response.json({"ok": True}))
    allowed = router.dispatch(Request("GET", "/v1/health", {"Origin": "https://example.test"}))
    denied = router.dispatch(Request("GET", "/v1/health", {"Origin": "https://evil.test"}))
    assert allowed.headers["access-control-allow-origin"] == "https://example.test"
    assert denied.status == 403


def test_router_normalizes_errors_and_handles_options():
    router = Router()

    @router.route("GET", "/v1/fail")
    def fail(request: Request) -> Response:
        raise APIError("bad_request", "Nope", 422)

    assert router.dispatch(Request("GET", "/v1/fail")).status == 422
    assert router.dispatch(Request("GET", "/v1/missing")).status == 404
    assert router.dispatch(Request("OPTIONS", "/v1/fail")).status == 204


def test_idempotency_replays_mutating_response():
    router = Router()
    calls = 0

    @router.route("POST", "/v1/runs")
    def create(request: Request) -> Response:
        nonlocal calls
        calls += 1
        return Response.json({"run": calls}, 201)

    request = Request("POST", "/v1/runs", {"Idempotency-Key": "same"})
    assert router.dispatch(request).body == router.dispatch(request).body
    assert calls == 1


def test_idempotency_reservation_prevents_concurrent_duplicate_mutation():
    router = Router()
    calls = 0
    entered = threading.Event()
    release = threading.Event()

    @router.route("POST", "/v1/runs")
    def create(request: Request) -> Response:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(2)
        return Response.json({"run": calls}, 201)

    request = Request("POST", "/v1/runs", {"Idempotency-Key": "same"})
    first = threading.Thread(target=lambda: router.dispatch(request))
    second = threading.Thread(target=lambda: router.dispatch(request))
    first.start()
    entered.wait(1)
    second.start()
    release.set()
    first.join()
    second.join()
    assert calls == 1


def test_idempotency_reservations_are_removed_after_completion():
    router = Router()

    router.route("POST", "/v1/runs")(lambda request: Response.json({"ok": True}, 201))

    for index in range(100):
        response = router.dispatch(Request("POST", "/v1/runs", {"Idempotency-Key": f"key-{index}"}))
        assert response.status == 201

    assert len(router.idempotency._inflight) == 0


def test_idempotency_replays_from_durable_sqlite_store_after_router_restart(tmp_path):
    persistence = SqliteIdempotencyStore(tmp_path / "api.sqlite3")
    first_router = Router(idempotency_persistence=persistence)
    calls = 0

    @first_router.route("POST", "/v1/runs")
    def create(request: Request) -> Response:
        nonlocal calls
        calls += 1
        return Response.json({"run": calls}, 201, {"x-result": "stored"})

    request = Request("POST", "/v1/runs", {"Idempotency-Key": "durable"})
    first = first_router.dispatch(request)

    second_router = Router(idempotency_persistence=SqliteIdempotencyStore(tmp_path / "api.sqlite3"))
    second_router.route("POST", "/v1/runs")(lambda request: Response.json({"run": 99}, 201))

    replay = second_router.dispatch(request)
    assert replay == first
    assert calls == 1


def test_pagination_has_opaque_stable_cursor():
    page = paginate([1, 2, 3], limit=2)
    assert page == {"items": [1, 2], "next_cursor": page["next_cursor"]}
    assert paginate([1, 2, 3], limit=2, cursor=page["next_cursor"]) == {"items": [3], "next_cursor": None}
    with pytest.raises(APIError, match="cursor"):
        decode_cursor("bad")
    assert "." in page["next_cursor"]
    with pytest.raises(APIError, match="cursor"):
        paginate([1, 2, 3], limit=2, cursor=page["next_cursor"][:-1])


def test_authenticated_route_populates_principal_context():
    from docs.api.auth import Principal, require_scopes

    router = Router()
    router.route(
        "GET",
        "/private",
        auth=lambda token: Principal("user-1", frozenset({"read"})) if token == "good" else None,
    )(lambda request: Response.json({"subject": request.principal.subject}))
    response = router.dispatch(Request("GET", "/private", {"Authorization": "Bearer good"}))
    assert response.status == 200
    assert json.loads(response.body) == {"subject": "user-1"}
    assert router.dispatch(Request("GET", "/private")).status == 401
    assert router.dispatch(Request("GET", "/private", {"Authorization": "Bearer bad"})).status == 401

    router.route(
        "GET",
        "/admin",
        auth=lambda token: Principal("user-1", frozenset({"read"})) if token == "good" else None,
    )(lambda request: Response.json({"subject": require_scopes(request.principal, "admin").subject}))
    assert router.dispatch(Request("GET", "/admin", {"Authorization": "Bearer good"})).status == 403
