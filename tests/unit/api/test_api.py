import io

import pytest

from docs.api.http import APIError, Request, Response, Router, error_response, paginate


def test_errors_are_safe_and_wsgi_uses_reason_phrase():
    response = error_response(APIError("internal", "secret", 500, details={"traceback": "hidden"}))
    assert response.status == 500
    assert b"traceback" not in response.body
    router = Router()
    router.route("GET", "/health")(lambda request: Response.json({"ok": True}))
    statuses = []
    body = router(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/health", "wsgi.input": io.BytesIO(), "CONTENT_LENGTH": "0"},
        lambda status, headers: statuses.append(status),
    )
    assert body
    assert statuses == ["200 OK"]


@pytest.mark.parametrize("length", ["-1", "not-a-number"])
def test_wsgi_rejects_malformed_content_length(length):
    router = Router()
    statuses = []
    router({"REQUEST_METHOD": "POST", "PATH_INFO": "/", "wsgi.input": io.BytesIO(b"x"), "CONTENT_LENGTH": length}, lambda s, h: statuses.append(s))
    assert statuses == ["400 Bad Request"]


def test_wsgi_bounds_unknown_content_length():
    router = Router(max_body_size=3)
    statuses = []
    router({"REQUEST_METHOD": "POST", "PATH_INFO": "/", "wsgi.input": io.BytesIO(b"abcd")}, lambda s, h: statuses.append(s))
    assert statuses == ["413 Payload Too Large"]


def test_method_not_allowed_includes_allow_header():
    router = Router()
    router.route("GET", "/resource")(lambda request: Response.json({}))
    response = router.dispatch(Request("POST", "/resource"))
    assert response.status == 405
    assert response.headers["allow"] == "GET"


def test_pagination_cursor_is_bound_to_query_and_expires():
    page = paginate([1, 2, 3], limit=2, resource="documents", query={"owner": "a"}, ttl=0)
    with pytest.raises(APIError, match="cursor"):
        paginate([1, 2, 3], limit=2, cursor=page["next_cursor"], resource="documents", query={"owner": "a"})
    page = paginate([1, 2, 3], limit=2, resource="documents", query={"owner": "a"})
    with pytest.raises(APIError, match="cursor"):
        paginate([1, 2, 3], limit=2, cursor=page["next_cursor"], resource="documents", query={"owner": "b"})
