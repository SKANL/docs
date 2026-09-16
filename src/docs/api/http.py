"""Small reusable WSGI HTTP primitives for the versioned API."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .auth import AuthError, Principal, TokenValidator, bearer_auth

_REASON = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
}


class APIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        *,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.details, self.headers = code, message, status, details, headers or {}


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | str | Mapping[str, Any] | None = None
    environ: Mapping[str, Any] = field(default_factory=dict)
    principal: Principal | None = None

    @property
    def query(self) -> Mapping[str, str]:
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    @property
    def route_path(self) -> str:
        return urlsplit(self.path).path

    def json(self, *, object_only: bool = False) -> Any:
        if self.body is None:
            value = None
        elif isinstance(self.body, Mapping):
            value = dict(self.body)
        else:
            try:
                value = json.loads(self.body.decode() if isinstance(self.body, bytes) else self.body)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                raise APIError("invalid_json", "Request body must be valid JSON") from exc
        if object_only and not isinstance(value, dict):
            raise APIError("invalid_json", "Request body must be a JSON object")
        return value


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str]

    @classmethod
    def json(cls, value: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> Response:
        return cls(
            status,
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode(),
            {"content-type": "application/json; charset=utf-8", **(headers or {})},
        )


Handler = Callable[[Request], Response]


def error_response(error: Exception) -> Response:
    if isinstance(error, AuthError):
        headers = dict(error.headers)
        if error.status == 401:
            headers.setdefault("WWW-Authenticate", 'Bearer realm="api"')
        return Response.json({"error": {"code": error.code, "message": error.message}}, error.status, headers)
    if isinstance(error, APIError):
        return Response.json({"error": {"code": error.code, "message": error.message}}, error.status, error.headers)
    return Response.json({"error": {"code": "internal_error", "message": "Internal server error"}}, 500)


_CURSOR_SECRET = b"docs-api-cursor-v1"


def _cursor(payload: dict[str, Any], secret: bytes = _CURSOR_SECRET) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _decode(cursor: str, secret: bytes = _CURSOR_SECRET) -> dict[str, Any]:
    try:
        encoded, supplied = cursor.split(".", 1)
        expected = hmac.new(secret, encoded.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        if not hmac.compare_digest(actual, expected):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise APIError("invalid_cursor", "cursor is invalid") from exc


def encode_cursor(offset: int) -> str:
    return _cursor({"offset": offset})


def decode_cursor(cursor: str) -> int:
    data = _decode(cursor)
    offset = data.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise APIError("invalid_cursor", "cursor is invalid")
    return offset


def paginate(
    items: Iterable[Any],
    *,
    limit: int = 20,
    cursor: str | None = None,
    max_limit: int = 100,
    resource: str = "",
    query: Mapping[str, str] | None = None,
    ttl: float = 300,
) -> dict[str, Any]:
    if not 1 <= limit <= max_limit:
        raise APIError("invalid_pagination", f"limit must be between 1 and {max_limit}")
    values = list(items)
    binding = hashlib.sha256(
        json.dumps([resource, sorted((query or {}).items())], separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    start = 0
    if cursor:
        data = _decode(cursor)
        raw_start = data.get("offset")
        start = raw_start if isinstance(raw_start, int) else -1
        if (
            data.get("binding") != binding
            or not isinstance(data.get("binding"), str)
            or not isinstance(data.get("expires"), (int, float))
            or not isinstance(start, int)
            or start < 0
            or time.time() >= data.get("expires", 0)
        ):
            raise APIError("invalid_cursor", "cursor is invalid or expired")
    page = values[start : start + limit]
    nxt = (
            _cursor({"offset": start + limit, "binding": binding, "expires": time.time() + ttl})
        if start + limit < len(values)
        else None
    )
    return {"items": page, "next_cursor": nxt}


class IdempotencyStore:
    def __init__(self, *, ttl: float = 86400, max_size: int = 10000) -> None:
        self._data: dict[str, tuple[float, Response]] = {}
        self._lock = threading.Lock()
        self._inflight: dict[str, tuple[threading.Lock, int]] = {}
        self.ttl = ttl
        self.max_size = max_size

    def get(self, key: str | None) -> Response | None:
        if not key:
            return None
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if item[0] <= time.monotonic():
                self._data.pop(key, None)
                return None
            return item[1]

    def put(self, key: str | None, response: Response) -> None:
        if key:
            with self._lock:
                if len(self._data) >= self.max_size:
                    self._data.pop(next(iter(self._data)))
                self._data[key] = (time.monotonic() + self.ttl, response)

    def reservation(self, key: str | None) -> threading.Lock | None:
        if not key:
            return None
        with self._lock:
            reservation = self._inflight.get(key)
            if reservation is None:
                reservation = (threading.Lock(), 0)
            self._inflight[key] = (reservation[0], reservation[1] + 1)
            return reservation[0]

    def release_reservation(self, key: str | None) -> None:
        if not key:
            return
        with self._lock:
            reservation = self._inflight.get(key)
            if reservation is None:
                return
            lock, users = reservation
            if users <= 1:
                self._inflight.pop(key, None)
            else:
                self._inflight[key] = (lock, users - 1)


class Router:
    def __init__(
        self,
        *,
        cors_origins: Iterable[str] | None = None,
        cors_origin: str | None = None,
        max_body_size: int = 1_048_576,
    ) -> None:
        self._routes: list[tuple[str, str, Handler, TokenValidator | None]] = []
        self.cors_origins = {origin.rstrip("/") for origin in (cors_origins or ([cors_origin] if cors_origin else [])) if origin}
        self.idempotency = IdempotencyStore()
        self.max_body_size = max_body_size

    def route(self, method: str, path: str, *, auth: TokenValidator | None = None):
        def decorator(handler):
            self._routes.append((method.upper(), path, handler, auth))
            return handler

        return decorator

    def dispatch(self, request: Request) -> Response:
        origin = next((v for k, v in request.headers.items() if k.lower() == "origin"), None)
        if origin and origin not in self.cors_origins:
            return self._cors(
                Response.json({"error": {"code": "cors_denied", "message": "Origin is not allowed"}}, 403), origin
            )
        if request.method.upper() == "OPTIONS":
            return self._cors(Response(204, b"", {}), origin)
        methods = [m for m, p, h, a in self._routes if p == request.route_path]
        for method, path, handler, validator in self._routes:
            if method == request.method.upper() and path == request.route_path:
                try:
                    key = next((v for k, v in request.headers.items() if k.lower() == "idempotency-key"), None)
                    idem_key = self._idem_key(request, key) if request.method.upper() in {"POST", "PUT", "PATCH"} else None
                    reservation = self.idempotency.reservation(idem_key)
                    try:
                        with reservation or _NullLock():
                            replay = self.idempotency.get(idem_key)
                            if replay:
                                response = replay
                            else:
                                authenticated = (
                                    Request(request.method, request.path, request.headers, request.body, request.environ,
                                            bearer_auth(request.headers, validator))
                                    if validator is not None else request
                                )
                                response = handler(authenticated)
                            if not replay:
                                self.idempotency.put(idem_key, response)
                    finally:
                        self.idempotency.release_reservation(idem_key)
                    return self._cors(response, origin)
                except Exception as exc:
                    return self._cors(error_response(exc), origin)
        if methods:
            return self._cors(
                error_response(
                    APIError(
                        "method_not_allowed",
                        "Method not allowed",
                        405,
                        headers={"allow": ", ".join(sorted(set(methods)))},
                    )
                ),
                origin,
            )
        return self._cors(error_response(APIError("not_found", "Resource not found", 404)), origin)

    def _idem_key(self, r: Request, key: str | None) -> str | None:
        if not key:
            return None
        principal = next((v for k, v in r.headers.items() if k.lower() in {"authorization", "x-principal"}), "")
        if isinstance(r.body, bytes):
            body = r.body.decode("utf-8", "replace")
        elif isinstance(r.body, str):
            body = r.body
        else:
            body = json.dumps(r.body, sort_keys=True, separators=(",", ":"))
        return (
            hashlib.sha256(f"{principal}\0{r.method.upper()}\0{r.route_path}\0{body}".encode()).hexdigest() + ":" + key
        )

    def _cors(self, response: Response, origin: str | None) -> Response:
        h = {
            **response.headers,
            "access-control-allow-headers": "Authorization, Content-Type, Idempotency-Key",
            "access-control-allow-methods": "GET, POST, PUT, PATCH, OPTIONS",
            "vary": "Origin",
        }
        if origin and origin in self.cors_origins:
            h["access-control-allow-origin"] = origin
        else:
            h.pop("access-control-allow-origin", None)
        return Response(response.status, response.body, h)

    def __call__(self, environ, start_response):
        raw_length = environ.get("CONTENT_LENGTH")
        try:
            length = 0 if raw_length in (None, "") else int(raw_length)
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            response = error_response(APIError("invalid_content_length", "Content length is invalid", 400))
        elif length > self.max_body_size:
            response = error_response(APIError("payload_too_large", "Request body is too large", 413))
        else:
            raw = environ.get("wsgi.input")
            body = raw.read(self.max_body_size + 1) if raw else None
            if body is not None and len(body) > self.max_body_size:
                response = error_response(APIError("payload_too_large", "Request body is too large", 413))
                start_response(f"{response.status} {_REASON.get(response.status, '')}", list(response.headers.items()))
                return [response.body]
            headers = {k[5:].replace("_", "-"): str(v) for k, v in environ.items() if k.startswith("HTTP_")}
            request = Request(
                str(environ.get("REQUEST_METHOD", "GET")), str(environ.get("PATH_INFO", "/")), headers, body, environ
            )
            response = self.dispatch(request)
        start_response(f"{response.status} {_REASON.get(response.status, '')}", list(response.headers.items()))
        return [response.body]


class _NullLock:
    def __enter__(self): return self
    def __exit__(self, *args): return False
