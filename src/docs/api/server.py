"""Standard-library deployment transport for the X20 WSGI application."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

from .http import APIError, Response, error_response

_LOG = logging.getLogger("docs.api.transport")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_REASON = {
    200: "OK",
    204: "No Content",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    413: "Payload Too Large",
    500: "Internal Server Error",
    503: "Service Unavailable",
}
_REQUEST_BODY_TIMEOUT = 5.0


@dataclass(frozen=True)
class _ApplicationResponse:
    status: int
    headers: list[tuple[str, str]]
    body: Iterable[bytes]
    content_length: int | None


class _ClosingIterator:
    """Adapt a WSGI iterable while closing it on exhaustion, error, or abort."""

    def __init__(self, source: Any) -> None:
        self._source = source
        self._iterator: Iterator[Any] = iter(source)
        self._closed = False

    def __iter__(self) -> _ClosingIterator:
        return self

    def __next__(self) -> bytes:
        try:
            chunk = next(self._iterator)
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self.close()
            raise
        return chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._source, "close", None)
        if close is not None:
            close()


@dataclass(frozen=True)
class TransportConfig:
    """Deployment-only settings; X20 routing and authentication stay in the app."""

    host: str = "127.0.0.1"
    port: int = 8000
    workspace: Path | None = None
    base_url: str = "/"
    max_request_body: int = 1_048_576
    cors_origins: tuple[str, ...] = ()
    graceful_shutdown_timeout: float = 10.0
    allow_public_bind: bool = False
    mode: str = "production"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> TransportConfig:
        origins = values.get("cors_origins", ())
        if isinstance(origins, str):
            origins = (origins,)
        return cls(
            host=str(values.get("host", cls.host)),
            port=int(values.get("port", cls.port)),
            workspace=Path(values["workspace"]) if values.get("workspace") else None,
            base_url=str(values.get("base_url", cls.base_url)),
            max_request_body=int(values.get("max_request_body", cls.max_request_body)),
            cors_origins=tuple(str(origin).rstrip("/") for origin in origins if str(origin).strip()),
            graceful_shutdown_timeout=float(
                values.get("graceful_shutdown_timeout", cls.graceful_shutdown_timeout)
            ),
            allow_public_bind=bool(values.get("allow_public_bind", cls.allow_public_bind)),
            mode=str(values.get("mode", cls.mode)).lower(),
        )

    def validate(self) -> None:
        if not self.host:
            raise ValueError("host must not be empty")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.max_request_body < 0:
            raise ValueError("max_request_body must not be negative")
        if self.graceful_shutdown_timeout < 0:
            raise ValueError("graceful_shutdown_timeout must not be negative")
        if self.mode not in {"production", "offline"}:
            raise ValueError("mode must be production or offline")
        if self.host.lower() not in _LOOPBACK and not self.allow_public_bind:
            raise ValueError(
                "public binding is disabled; set allow_public_bind=true explicitly before binding outside loopback"
            )

    @property
    def base_path(self) -> str:
        """Return the reverse-proxy path prefix represented by ``base_url``."""
        path = urlsplit(self.base_url).path or "/"
        normalized = "/" + path.strip("/")
        return "/" if normalized == "/" else normalized.rstrip("/")


class X20Transport:
    """Bounded WSGI middleware around an existing :class:`X20Application`."""

    def __init__(
        self,
        application: Callable[..., Any],
        config: TransportConfig,
        *,
        ready_check: Callable[[], bool] | None = None,
    ) -> None:
        config.validate()
        self.application = application
        self.config = config
        self.ready_check = ready_check or (lambda: True)

    def __call__(self, environ: Mapping[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        started = time.monotonic()
        request_id = self._request_id(environ)
        path = self._external_path(environ)
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        origin = self._header(environ, "origin")
        route = self._route_label(path)
        application_response: _ApplicationResponse | None = None
        response: Response | None = None
        try:
            if origin and origin.rstrip("/") not in self.config.cors_origins:
                response = Response.json(
                    {"error": {"code": "cors_denied", "message": "Origin is not allowed", "details": {}}},
                    403,
                )
            elif method == "OPTIONS" and origin:
                response = Response(204, b"", {})
            elif path == "/healthz":
                response = Response.json({"status": "ok"})
            elif path == "/readyz":
                ready = bool(self.ready_check())
                response = Response.json({"status": "ready" if ready else "not_ready"}, 200 if ready else 503)
            else:
                application_response = self._dispatch_application(environ, path, request_id)
        except Exception as exc:
            response = error_response(exc)
            if isinstance(exc, APIError) and exc.code in {
                "invalid_content_length",
                "payload_too_large",
                "unsupported_transfer_encoding",
                "incomplete_request_body",
            }:
                response = Response(response.status, response.body, {**response.headers, "Connection": "close"})

        if application_response is not None:
            headers = self._with_transport_headers(
                application_response.headers,
                request_id,
                origin,
                content_length=application_response.content_length,
            )
            status = application_response.status
            body = application_response.body
        else:
            assert response is not None
            headers = self._with_transport_headers(response.headers.items(), request_id, origin, content_length=len(response.body))
            status = response.status
            body = [response.body]
        try:
            start_response(f"{status} {_REASON.get(status, '')}".rstrip(), headers)
        except BaseException:
            close = getattr(body, "close", None)
            if close is not None:
                close()
            raise
        self._log_access(method, route, status, request_id, started)
        return body

    def _dispatch_application(
        self, environ: Mapping[str, Any], path: str, request_id: str
    ) -> _ApplicationResponse:
        body = self._read_request_body(environ)
        child_environ = dict(environ)
        child_environ["PATH_INFO"] = path
        child_environ["wsgi.input"] = BytesIO(body)
        child_environ["CONTENT_LENGTH"] = str(len(body))
        child_environ["HTTP_X_REQUEST_ID"] = request_id
        child_environ["DOCS_WORKSPACE"] = str(self.config.workspace) if self.config.workspace else ""
        child_environ["DOCS_BASE_URL"] = self.config.base_url

        captured: dict[str, Any] = {}

        def capture(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
            del exc_info
            captured["status"] = status
            captured["headers"] = list(headers)

        result = self.application(child_environ, capture)
        source = (result,) if isinstance(result, (bytes, bytearray)) else result
        body_iterator = _ClosingIterator(source)
        content_length = self._known_content_length(result)
        status = int(str(captured.get("status", "500")).split(" ", 1)[0])
        return _ApplicationResponse(
            status,
            list(captured.get("headers", [])),
            body_iterator,
            content_length,
        )

    def _read_request_body(self, environ: Mapping[str, Any]) -> bytes:
        transfer_encoding = self._header(environ, "transfer-encoding")
        if transfer_encoding and transfer_encoding.lower().strip() != "identity":
            raise APIError(
                "unsupported_transfer_encoding",
                "Transfer-Encoding is not supported",
                400,
            )
        raw_length = environ.get("CONTENT_LENGTH")
        try:
            length = 0 if raw_length in (None, "") else int(raw_length)
        except (TypeError, ValueError) as exc:
            raise APIError("invalid_content_length", "Content length is invalid", 400) from exc
        if length < 0:
            raise APIError("invalid_content_length", "Content length is invalid", 400)
        if length > self.config.max_request_body:
            raise APIError("payload_too_large", "Request body is too large", 413)

        raw = environ.get("wsgi.input")
        if length == 0:
            return b""
        if raw is None or not hasattr(raw, "read"):
            raise APIError("incomplete_request_body", "Request body is incomplete", 400)
        try:
            body = raw.read(length)
        except TimeoutError as exc:
            raise APIError("incomplete_request_body", "Request body is incomplete", 400) from exc
        if not isinstance(body, (bytes, bytearray)) or len(body) != length:
            raise APIError("incomplete_request_body", "Request body is incomplete", 400)
        return bytes(body)

    @staticmethod
    def _known_content_length(result: Any) -> int | None:
        if isinstance(result, (bytes, bytearray)):
            return len(result)
        if isinstance(result, (list, tuple)):
            try:
                return sum(len(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")) for chunk in result)
            except Exception:
                return None
        return None

    def _with_transport_headers(
        self,
        response_headers: Iterable[tuple[str, str]],
        request_id: str,
        origin: str | None,
        *,
        content_length: int | None,
    ) -> list[tuple[str, str]]:
        headers = self._deduplicate_headers(response_headers)
        if not self._has_header(headers, "Content-Type"):
            self._set_header(headers, "Content-Type", "application/json; charset=utf-8")
        self._set_header(headers, "X-Request-ID", request_id)
        if not self._has_header(headers, "Connection"):
            self._set_header(headers, "Connection", "keep-alive")
        if content_length is not None and not self._has_header(headers, "Content-Length"):
            self._set_header(headers, "Content-Length", str(content_length))
        elif not self._has_header(headers, "Content-Length"):
            self._set_header(headers, "Transfer-Encoding", "chunked")
        if self._header_value(headers, "Content-Type").lower().startswith("text/event-stream"):
            self._set_header(headers, "Cache-Control", "no-cache")
        self._set_header(headers, "access-control-allow-headers", "Authorization, Content-Type, Idempotency-Key, X-Request-ID")
        self._set_header(headers, "access-control-allow-methods", "GET, POST, PUT, PATCH, OPTIONS")
        self._set_header(headers, "vary", "Origin")
        if origin and origin.rstrip("/") in self.config.cors_origins:
            self._set_header(headers, "access-control-allow-origin", origin)
        else:
            self._remove_header(headers, "access-control-allow-origin")
        return headers

    @staticmethod
    def _deduplicate_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        seen: set[str] = set()
        for key, value in headers:
            normalized = str(key).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append((str(key), str(value)))
        return result

    @staticmethod
    def _has_header(headers: Iterable[tuple[str, str]], name: str) -> bool:
        normalized = name.lower()
        return any(key.lower() == normalized for key, _ in headers)

    @staticmethod
    def _header_value(headers: Iterable[tuple[str, str]], name: str) -> str:
        normalized = name.lower()
        return next((value for key, value in headers if key.lower() == normalized), "")

    @staticmethod
    def _set_header(headers: list[tuple[str, str]], name: str, value: str) -> None:
        normalized = name.lower()
        for index, (key, _) in enumerate(headers):
            if key.lower() == normalized:
                headers[index] = (key, value)
                return
        headers.append((name, value))

    @staticmethod
    def _remove_header(headers: list[tuple[str, str]], name: str) -> None:
        normalized = name.lower()
        headers[:] = [(key, value) for key, value in headers if key.lower() != normalized]

    def _external_path(self, environ: Mapping[str, Any]) -> str:
        path = urlsplit(str(environ.get("PATH_INFO", "/"))).path or "/"
        base = self.config.base_path
        if base != "/":
            if path == base:
                return "/"
            if not path.startswith(f"{base}/"):
                return path
            path = path[len(base) :]
        return path or "/"

    @staticmethod
    def _header(environ: Mapping[str, Any], name: str) -> str | None:
        key = f"HTTP_{name.upper().replace('-', '_')}"
        value = environ.get(key)
        if value is not None:
            return str(value)
        normalized = key.upper()
        for candidate, candidate_value in environ.items():
            if str(candidate).upper() == normalized and candidate_value is not None:
                return str(candidate_value)
        return None

    @staticmethod
    def _request_id(environ: Mapping[str, Any]) -> str:
        supplied = X20Transport._header(environ, "x-request-id")
        return supplied if supplied and _REQUEST_ID.fullmatch(supplied) else uuid4().hex

    @staticmethod
    def _route_label(path: str) -> str:
        pieces = [piece for piece in path.strip("/").split("/") if piece]
        return "/" + "/".join(pieces[:2]) if pieces else "/"

    @staticmethod
    def _log_access(method: str, route: str, status: int, request_id: str, started: float) -> None:
        _LOG.info(
            json.dumps(
                {
                    "event": "http_request",
                    "method": method,
                    "route": route,
                    "status": status,
                    "request_id": request_id,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                },
                separators=(",", ":"),
            )
        )


class GracefulHTTPServer(ThreadingHTTPServer):
    """Threading server with explicit shutdown state for embedding and tests."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], transport: X20Transport) -> None:
        self.transport = transport
        self.shutdown_timeout = transport.config.graceful_shutdown_timeout
        self.shutdown_requested = False
        self.shutdown_timed_out = False
        self._active_requests = 0
        self._request_condition = threading.Condition()
        super().__init__(address, _RequestHandler)

    def _begin_request(self) -> None:
        with self._request_condition:
            self._active_requests += 1

    def _finish_request(self) -> None:
        with self._request_condition:
            self._active_requests = max(0, self._active_requests - 1)
            self._request_condition.notify_all()

    def shutdown(self) -> None:
        with self._request_condition:
            if self.shutdown_requested:
                return
            self.shutdown_requested = True
        deadline = time.monotonic() + self.shutdown_timeout
        stopper = threading.Thread(target=super().shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._request_condition:
            while self._active_requests:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.shutdown_timed_out = True
                    break
                self._request_condition.wait(timeout=remaining)
        if stopper.is_alive():
            self.shutdown_timed_out = True


def create_app(
    application: Callable[..., Any],
    config: TransportConfig | Mapping[str, Any] | None = None,
    *,
    ready_check: Callable[[], bool] | None = None,
) -> X20Transport:
    """Build the same transport for embedded/offline and remote deployments."""
    resolved = config if isinstance(config, TransportConfig) else TransportConfig.from_mapping(config or {})
    _require_production_auth(application, resolved)
    return X20Transport(application, resolved, ready_check=ready_check)


def create_server(
    application: Callable[..., Any], config: TransportConfig | Mapping[str, Any] | None = None
) -> GracefulHTTPServer:
    if isinstance(application, X20Transport):
        resolved = application.config if config is None else (
            config if isinstance(config, TransportConfig) else TransportConfig.from_mapping(config)
        )
        _require_production_auth(application.application, resolved)
        transport = application if resolved == application.config else X20Transport(
            application.application, resolved, ready_check=application.ready_check
        )
    else:
        transport = create_app(application, config)
        resolved = transport.config
    return GracefulHTTPServer((resolved.host, resolved.port), transport)


def _require_production_auth(application: Callable[..., Any], config: TransportConfig) -> None:
    if config.mode == "production" and getattr(application, "auth", None) is None:
        raise ValueError("production mode requires authentication")


def serve(server: GracefulHTTPServer, *, once: bool = False) -> None:
    """Serve until shutdown; ``once`` handles one request for deterministic tests."""
    try:
        if once:
            server.handle_request()
        else:
            server.serve_forever()
    finally:
        server.server_close()


run_server = serve


class _RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self) -> None:
        try:
            super().handle()
        except (TimeoutError, BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch(head_only=True)

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def _dispatch(self, *, head_only: bool = False) -> None:
        captured: dict[str, Any] = {}
        server = cast(GracefulHTTPServer, self.server)
        server._begin_request()
        previous_timeout = self.connection.gettimeout()

        def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
            captured["status"] = status
            captured["headers"] = headers

        try:
            self.connection.settimeout(_REQUEST_BODY_TIMEOUT)
            content_lengths = self.headers.get_all("Content-Length", [])
            if content_lengths and len({value.strip() for value in content_lengths}) > 1:
                content_length = "invalid"
            else:
                content_length = content_lengths[0] if content_lengths else ""
            parsed_path = urlsplit(self.path)
            environ = {
                "REQUEST_METHOD": self.command,
                "SCRIPT_NAME": "",
                "PATH_INFO": parsed_path.path or "/",
                "QUERY_STRING": parsed_path.query,
                "SERVER_NAME": server.server_address[0],
                "SERVER_PORT": str(server.server_address[1]),
                "SERVER_PROTOCOL": self.request_version,
                "SERVER_SOFTWARE": self.version_string(),
                "REMOTE_ADDR": self.client_address[0],
                "REMOTE_PORT": str(self.client_address[1]),
                "wsgi.version": (1, 0),
                "wsgi.url_scheme": "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http",
                "wsgi.input": self.rfile,
                "wsgi.errors": sys.stderr,
                "wsgi.multithread": True,
                "wsgi.multiprocess": False,
                "wsgi.run_once": False,
                "CONTENT_LENGTH": content_length,
            }
            if self.headers.get("Content-Type"):
                environ["CONTENT_TYPE"] = self.headers["Content-Type"]
            for key, value in self.headers.items():
                normalized = key.upper().replace("-", "_")
                if normalized in {"CONTENT_LENGTH", "CONTENT_TYPE"}:
                    continue
                environ[f"HTTP_{normalized}"] = value
            result = server.transport(environ, start_response)
            self.connection.settimeout(previous_timeout)
            status = int(str(captured.get("status", "500")).split(" ", 1)[0])
            self.send_response(status)
            sent = set()
            for key, value in captured.get("headers", []):
                normalized = key.lower()
                if normalized in sent:
                    continue
                self.send_header(key, value)
                sent.add(normalized)
            if "connection" not in sent:
                self.send_header("Connection", "keep-alive")
            self.end_headers()
            chunked = any(
                key.lower() == "transfer-encoding" and value.lower() == "chunked"
                for key, value in captured.get("headers", [])
            )
            if not head_only:
                for chunk in result:
                    if chunked:
                        self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                        self.wfile.write(chunk)
                        self.wfile.write(b"\r\n")
                    else:
                        self.wfile.write(chunk)
                    self.wfile.flush()
                if chunked:
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
            close = getattr(result, "close", None)
            if close is not None:
                close()
        finally:
            if "result" in locals():
                close = getattr(result, "close", None)
                if close is not None:
                    close()
            self.connection.settimeout(previous_timeout)
            server._finish_request()

    def log_message(self, format: str, *args: Any) -> None:
        return


def _load_json_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("API configuration must be a JSON object")
    return value


def _load_factory(spec: str) -> Callable[[TransportConfig], Callable[..., Any]]:
    try:
        module_name, attribute = spec.split(":", 1)
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ValueError, ImportError, AttributeError) as exc:
        raise ValueError("application_factory must use an importable module:attribute") from exc
    if not callable(factory):
        raise ValueError("application_factory must be callable")
    return factory


def _compose_application(
    factory: Callable[[TransportConfig], Callable[..., Any]],
    config: TransportConfig,
) -> Callable[..., Any]:
    application = factory(config)
    if config.mode == "production" and getattr(application, "auth", None) is None:
        raise ValueError("production mode requires authentication to be injected by application_factory")
    return application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs-api", description="Serve an existing X20 WSGI application")
    parser.add_argument("--config", type=Path, required=True, help="JSON deployment configuration")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--once", action="store_true", help="serve one request and exit")
    parser.add_argument("--allow-public-bind", action="store_true", help="explicitly allow non-loopback binding")
    args = parser.parse_args(argv)
    raw = _load_json_config(args.config)
    transport_values = dict(raw.get("transport", raw))
    if args.host is not None:
        transport_values["host"] = args.host
    if args.port is not None:
        transport_values["port"] = args.port
    if args.allow_public_bind:
        transport_values["allow_public_bind"] = True
    config = TransportConfig.from_mapping(transport_values)
    factory = _load_factory(str(raw.get("application_factory", "")))
    application = create_app(_compose_application(factory, config), config)
    server = create_server(application)
    previous = {}

    def request_shutdown(signum: int, frame: Any) -> None:
        del signum, frame
        server.shutdown()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            previous[name] = signal.signal(getattr(signal, name), request_shutdown)
    try:
        serve(server, once=args.once)
    finally:
        for name, handler in previous.items():
            signal.signal(getattr(signal, name), handler)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
