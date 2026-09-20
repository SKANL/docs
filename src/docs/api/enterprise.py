"""Small, dependency-free primitives for enterprise API boundaries."""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http import APIError


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float = 0.0


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    """Thread-safe token-bucket limiter keyed by an arbitrary tenant/client id."""

    def __init__(
        self,
        *,
        rate: float,
        capacity: int,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if rate <= 0 or capacity <= 0 or max_keys <= 0:
            raise ValueError("rate, capacity, and max_keys must be positive")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, *, cost: float = 1.0) -> RateLimitResult:
        if not key:
            raise ValueError("key must not be empty")
        if cost <= 0 or cost > self.capacity:
            raise ValueError("cost must be greater than zero and no greater than capacity")

        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self.capacity, now)
                self._buckets[key] = bucket
                self._trim()
            else:
                bucket.tokens = min(self.capacity, bucket.tokens + max(0.0, now - bucket.updated_at) * self.rate)
                bucket.updated_at = now
                self._buckets.move_to_end(key)

            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return RateLimitResult(True, int(bucket.tokens), 0.0)

            retry_after = (cost - bucket.tokens) / self.rate
            return RateLimitResult(False, int(bucket.tokens), retry_after)

    def _trim(self) -> None:
        while len(self._buckets) > self._max_keys:
            self._buckets.popitem(last=False)


class WorkspacePathError(ValueError):
    """Raised when a requested path leaves its configured workspace."""


def safe_workspace_path(workspace: str | Path, requested: str | Path) -> Path:
    """Return a workspace-contained path, rejecting traversal and symlink escapes."""

    root = Path(workspace).expanduser().resolve()
    relative = Path(requested)
    if relative.is_absolute():
        raise WorkspacePathError("path must be relative to the workspace")

    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathError("path leaves the workspace") from exc
    return candidate


def normalize_error(error: Exception) -> dict[str, dict[str, Any]]:
    """Convert known and unexpected exceptions to a stable, safe error payload."""

    if isinstance(error, APIError):
        details = error.details if error.details is not None else {}
        return {"error": {"code": error.code, "message": error.message, "details": details}}
    return {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "details": {},
        }
    }


def encode_sse_event(
    event: str | None,
    data: Any,
    *,
    event_id: str | None = None,
    retry: int | None = None,
) -> str:
    """Encode one SSE event with deterministic JSON for structured data."""

    for value, label in ((event, "event"), (event_id, "id")):
        if value is not None and any(char in value for char in "\r\n"):
            raise ValueError(f"{label} must not contain newlines")
    if retry is not None and retry < 0:
        raise ValueError("retry must not be negative")

    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    if retry is not None:
        lines.append(f"retry: {retry}")
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"), sort_keys=True)
    lines.extend(f"data: {line}" for line in payload.splitlines() or [""])
    return "\n".join(lines) + "\n\n"
