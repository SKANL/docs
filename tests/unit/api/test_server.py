import io
import json
import re
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.request import urlopen

import pytest

from docs.api.server import (
    TransportConfig,
    X20Transport,
    create_server,
    serve,
)


def invoke(app, path="/v1/example", *, method="GET", body=b"", headers=None):
    captured = {}
    request_headers = {"CONTENT_LENGTH": str(len(body))}
    for key, value in (headers or {}).items():
        request_headers[f"HTTP_{key.upper().replace('-', '_')}"] = value
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(body),
        **request_headers,
    }
    chunks = []

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    result = app(environ, start_response)
    try:
        chunks.extend(result)
    finally:
        close = getattr(result, "close", None)
        if close:
            close()
    return captured, b"".join(chunks)


def json_body(body):
    return json.loads(body.decode())


def echo_app(environ, start_response):
    request_id = environ.get("HTTP_X_REQUEST_ID", "")
    payload = json.dumps(
        {
            "method": environ["REQUEST_METHOD"],
            "path": environ["PATH_INFO"],
            "request_id": request_id,
            "body": environ["wsgi.input"].read().decode(),
        },
        separators=(",", ":"),
    ).encode()
    start_response("200 OK", [("Content-Type", "application/json")])
    return [payload]


class UnexpectedRead:
    def read(self, size=-1):
        raise AssertionError("bodyless request must not read from wsgi.input")


def test_transport_rejects_request_bodies_over_configured_limit():
    app = X20Transport(echo_app, TransportConfig(max_request_body=3))

    captured, body = invoke(app, body=b"four")

    assert captured["status"].startswith("413")
    assert json_body(body)["error"]["code"] == "payload_too_large"
    assert captured["headers"]["Connection"] == "close"


def test_transport_applies_cors_to_allowed_origin_and_rejects_other_origins():
    app = X20Transport(echo_app, TransportConfig(cors_origins=("https://allowed.test",)))

    allowed, _ = invoke(app, headers={"Origin": "https://allowed.test"})
    denied, denied_body = invoke(app, headers={"Origin": "https://blocked.test"})

    assert allowed["headers"]["access-control-allow-origin"] == "https://allowed.test"
    assert denied["status"].startswith("403")
    assert json_body(denied_body)["error"]["code"] == "cors_denied"


def test_health_and_readiness_are_transport_endpoints():
    called = False

    def app(environ, start_response):
        nonlocal called
        called = True
        return echo_app(environ, start_response)

    transport = X20Transport(app, TransportConfig(), ready_check=lambda: False)

    health, health_body = invoke(transport, "/healthz")
    readiness, readiness_body = invoke(transport, "/readyz")

    assert health["status"].startswith("200")
    assert json_body(health_body) == {"status": "ok"}
    assert readiness["status"].startswith("503")
    assert json_body(readiness_body) == {"status": "not_ready"}
    assert called is False


def test_health_and_readiness_follow_configured_base_path():
    transport = X20Transport(echo_app, TransportConfig(base_url="https://example.test/docs"))

    health, health_body = invoke(transport, "/docs/healthz")
    readiness, readiness_body = invoke(transport, "/docs/readyz")

    assert health["status"].startswith("200")
    assert json_body(health_body) == {"status": "ok"}
    assert readiness["status"].startswith("200")
    assert json_body(readiness_body) == {"status": "ready"}


def test_transport_preserves_request_id_and_adds_one_when_missing():
    transport = X20Transport(echo_app, TransportConfig())

    supplied, supplied_body = invoke(transport, headers={"X-Request-ID": "request-123"})
    generated, generated_body = invoke(transport)

    assert supplied["headers"]["X-Request-ID"] == "request-123"
    assert json_body(supplied_body)["request_id"] == "request-123"
    assert generated["headers"]["X-Request-ID"]
    assert json_body(generated_body)["request_id"] == generated["headers"]["X-Request-ID"]


def test_transport_dispatches_to_existing_wsgi_application_and_normalizes_errors():
    transport = X20Transport(echo_app, TransportConfig())

    captured, body = invoke(transport, "/v1/example", method="POST", body=b"payload")

    assert captured["status"].startswith("200")
    assert json_body(body)["path"] == "/v1/example"
    assert captured["headers"]["Content-Length"] == str(len(body))

    def broken(environ, start_response):
        raise RuntimeError("secret token must not escape")

    broken_response, broken_body = invoke(X20Transport(broken, TransportConfig()))
    assert broken_response["status"].startswith("500")
    assert json_body(broken_body)["error"] == {
        "code": "internal_error",
        "message": "Internal server error",
        "details": {},
    }
    assert b"secret token" not in broken_body


def test_sse_response_has_event_content_type_and_keep_alive_length():
    def sse(environ, start_response):
        event = b"id: 1\nevent: progress\ndata: {}\n\n"
        start_response("200 OK", [("Content-Type", "text/event-stream"), ("Cache-Control", "no-cache")])
        return [event]

    captured, body = invoke(X20Transport(sse, TransportConfig()), "/v1/progress")

    assert captured["headers"]["Content-Type"] == "text/event-stream"
    assert captured["headers"]["Cache-Control"] == "no-cache"
    assert captured["headers"]["Connection"] == "keep-alive"
    assert captured["headers"]["Content-Length"] == str(len(body))


def test_public_binding_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="public binding"):
        TransportConfig(host="0.0.0.0").validate()

    TransportConfig(host="0.0.0.0", allow_public_bind=True).validate()


def test_graceful_shutdown_stops_threading_server():
    transport = X20Transport(echo_app, TransportConfig())
    server = create_server(transport, TransportConfig(host="127.0.0.1", port=0))
    thread = threading.Thread(target=serve, args=(server,), daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while server.server_address[1] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    server.shutdown()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert server.shutdown_requested is True


def test_once_server_handles_a_real_http_request_and_closes():
    server = create_server(X20Transport(echo_app, TransportConfig()), TransportConfig(port=0))
    thread = threading.Thread(target=serve, args=(server,), kwargs={"once": True}, daemon=True)
    thread.start()

    with urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/example") as response:
        assert response.status == 200
        assert response.headers["X-Request-ID"]
        body = json_body(response.read())
        assert body["method"] == "GET"
        assert body["path"] == "/v1/example"
        assert body["body"] == ""

    thread.join(timeout=2)
    assert not thread.is_alive()


def test_config_loads_workspace_and_base_url(tmp_path: Path):
    config = TransportConfig.from_mapping(
        {
            "host": "127.0.0.1",
            "port": 8123,
            "workspace": str(tmp_path),
            "base_url": "https://api.example.test/docs",
            "max_request_body": 1234,
            "cors_origins": ["https://studio.example.test"],
            "graceful_shutdown_timeout": 4,
        }
    )

    assert config.workspace == tmp_path
    assert config.base_url == "https://api.example.test/docs"
    assert config.max_request_body == 1234
    assert config.cors_origins == ("https://studio.example.test",)
    assert config.graceful_shutdown_timeout == 4


def test_wsgi_generators_are_not_eagerly_consumed():
    first_chunk = threading.Event()
    release_second = threading.Event()

    def streaming_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/event-stream")])

        def events() -> Iterator[bytes]:
            first_chunk.set()
            yield b"data: first\n\n"
            assert release_second.wait(1)
            yield b"data: second\n\n"

        return events()

    captured = {}
    result = X20Transport(streaming_app, TransportConfig())(
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/v1/events",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(),
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )

    iterator = iter(result)
    assert next(iterator) == b"data: first\n\n"
    assert first_chunk.is_set()
    release_second.set()
    assert next(iterator) == b"data: second\n\n"
    result.close()


def test_bodyless_wsgi_request_does_not_read_input():
    captured, body = invoke(
        X20Transport(echo_app, TransportConfig()),
        headers={},
    )
    assert captured["status"].startswith("200")
    assert json_body(body)["body"] == ""


def test_malformed_content_length_is_rejected_without_reading_input():
    transport = X20Transport(echo_app, TransportConfig())
    captured = {}
    result = transport(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/example",
            "CONTENT_LENGTH": "not-a-number",
            "wsgi.input": UnexpectedRead(),
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )

    assert captured["status"].startswith("400")
    assert json_body(b"".join(result))["error"]["code"] == "invalid_content_length"


def test_declared_body_is_read_once_with_exact_bound_and_short_body_is_rejected():
    class RecordingInput:
        def __init__(self, body):
            self.body = body
            self.sizes = []

        def read(self, size=-1):
            self.sizes.append(size)
            return self.body[:size]

    complete = RecordingInput(b"abc")
    captured = {}
    result = X20Transport(echo_app, TransportConfig(max_request_body=3))(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/example",
            "CONTENT_LENGTH": "3",
            "wsgi.input": complete,
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )
    assert captured["status"].startswith("200")
    assert json_body(b"".join(result))["body"] == "abc"
    assert complete.sizes == [3]

    short = RecordingInput(b"ab")
    captured = {}
    result = X20Transport(echo_app, TransportConfig())(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/example",
            "CONTENT_LENGTH": "3",
            "wsgi.input": short,
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )

    assert captured["status"].startswith("400")
    assert json_body(b"".join(result))["error"]["code"] == "incomplete_request_body"
    assert short.sizes == [3]

    transport = X20Transport(echo_app, TransportConfig())
    captured = {}
    result = transport(
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/v1/example",
            "wsgi.input": UnexpectedRead(),
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )
    body = b"".join(result)
    assert captured["status"].startswith("200")
    assert json_body(body)["body"] == ""


def test_chunked_request_is_rejected_without_reading_the_body():
    transport = X20Transport(echo_app, TransportConfig())
    captured = {}
    result = transport(
        {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/example",
            "HTTP_TRANSFER_ENCODING": "chunked",
            "wsgi.input": UnexpectedRead(),
        },
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )

    assert captured["status"].startswith("400")
    assert json_body(b"".join(result))["error"]["code"] == "unsupported_transfer_encoding"
    assert captured["headers"]["Connection"] == "close"


def test_shutdown_wait_is_bounded_by_configured_timeout():
    server = create_server(
        X20Transport(echo_app, TransportConfig(graceful_shutdown_timeout=0.05)),
        TransportConfig(port=0, graceful_shutdown_timeout=0.05),
    )
    thread = threading.Thread(target=serve, args=(server,), daemon=True)
    thread.start()
    server._begin_request()
    started = time.monotonic()
    server.shutdown()
    elapsed = time.monotonic() - started
    server._finish_request()
    thread.join(timeout=1)

    assert elapsed < 0.5
    assert server.shutdown_timed_out is True
    assert not thread.is_alive()
    server.shutdown()


def test_http_handler_supplies_standard_wsgi_environ_keys():
    captured_environ = {}

    def app(environ, start_response):
        captured_environ.update(environ)
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]

    server = create_server(X20Transport(app, TransportConfig()), TransportConfig(port=0))
    thread = threading.Thread(target=serve, args=(server,), kwargs={"once": True}, daemon=True)
    thread.start()
    with urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/example") as response:
        assert response.status == 200
    thread.join(timeout=1)

    assert captured_environ["wsgi.version"] == (1, 0)
    assert captured_environ["wsgi.multithread"] is True
    assert captured_environ["wsgi.multiprocess"] is False
    assert captured_environ["wsgi.run_once"] is False
    assert captured_environ["SCRIPT_NAME"] == ""
    assert captured_environ["QUERY_STRING"] == ""
    assert captured_environ["CONTENT_LENGTH"] == "0"
    assert captured_environ["REMOTE_PORT"]


def test_sse_streams_over_a_real_socket_without_buffering():
    first_sent = threading.Event()
    release_second = threading.Event()

    def streaming_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/event-stream")])

        def events() -> Iterator[bytes]:
            first_sent.set()
            yield b"data: first\n\n"
            assert release_second.wait(1)
            yield b"data: second\n\n"

        return events()

    server = create_server(X20Transport(streaming_app, TransportConfig()), TransportConfig(port=0))
    thread = threading.Thread(target=serve, args=(server,), daemon=True)
    thread.start()
    with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=1) as client:
        client.sendall(b"GET /v1/events HTTP/1.1\r\nHost: localhost\r\n\r\n")
        received = b""
        while b"\r\n\r\n" not in received:
            received += client.recv(4096)
        assert b"text/event-stream" in received
        assert b"no-cache" in received
        client.settimeout(1)
        while b"data: first\n\n" not in received:
            received += client.recv(4096)
        assert first_sent.is_set()
        release_second.set()
    server.shutdown()
    thread.join(timeout=2)

    assert not thread.is_alive()


def test_closing_stream_result_closes_application_iterator():
    closed = threading.Event()

    def streaming_app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/event-stream")])

        class Events:
            def __iter__(self):
                yield b"data: first\n\n"
                raise AssertionError("the iterator must be closed before it is exhausted")

            def close(self):
                closed.set()

        return Events()

    captured = {}
    result = X20Transport(streaming_app, TransportConfig())(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/v1/events", "wsgi.input": io.BytesIO()},
        lambda status, headers, exc_info=None: captured.update(status=status, headers=dict(headers)),
    )
    assert next(iter(result)) == b"data: first\n\n"
    result.close()
    assert closed.is_set()


def test_transport_deduplicates_case_insensitive_default_headers():
    def app(environ, start_response):
        start_response(
            "200 OK",
            [("content-type", "text/plain"), ("Content-Type", "application/json"), ("content-length", "2")],
        )
        return [b"ok"]

    captured, body = invoke(X20Transport(app, TransportConfig()))
    header_names = [name.lower() for name in captured["headers"]]

    assert body == b"ok"
    assert header_names.count("content-type") == 1
    assert captured["headers"]["content-type"] == "text/plain"
    assert header_names.count("content-length") == 1
    assert captured["headers"]["content-length"] == "2"


def test_transport_generates_one_stable_request_id_and_replaces_duplicates():
    def app(environ, start_response):
        start_response("200 OK", [("x-request-id", "wrong"), ("X-Request-ID", "also-wrong")])
        return [environ["HTTP_X_REQUEST_ID"].encode()]

    captured, body = invoke(X20Transport(app, TransportConfig()))
    request_ids = [value for key, value in captured["headers"].items() if key.lower() == "x-request-id"]

    assert len(request_ids) == 1
    assert request_ids[0].encode() == body
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_ids[0])
