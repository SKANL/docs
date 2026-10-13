"""Small, dependency-free primitives for enterprise API boundaries."""

from __future__ import annotations

import json
from typing import Any

from .http import APIError


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
