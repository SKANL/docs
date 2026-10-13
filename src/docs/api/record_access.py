"""Stateless helpers the route groups share to read, filter and page store records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .http import APIError, Request, Response, paginate


def as_dict(value: Any) -> Any:
    return value.to_dict() if hasattr(value, "to_dict") else dict(value) if isinstance(value, Mapping) else value


def store_items(store: Any, method: str, *args: Any) -> list[Any]:
    callback = getattr(store, method, None) if store is not None else None
    if not callable(callback):
        return []
    result = callback(*args)
    return list(result or [])


def store_get(store: Any, value: str, *keys: str) -> Any:
    getter = getattr(store, "get", None) if store is not None else None
    if callable(getter):
        result = getter(value)
        if result is not None:
            return result
    for item in store_items(store, "list"):
        data = as_dict(item)
        if any(str(data.get(key, "")) == value for key in keys):
            return item
    return None


def filter_items(items: Iterable[Any], query: Mapping[str, str]) -> list[Any]:
    filters = {k: v for k, v in query.items() if k not in {"limit", "cursor", "workspace_id"}}
    return [item for item in items if all(str(as_dict(item).get(key)) == value for key, value in filters.items())]


def page_response(items: Iterable[Any], request: Request, resource: str) -> Response:
    query = request.query
    raw_limit = query.get("limit", "20")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise APIError("invalid_pagination", "limit must be an integer") from exc
    page = paginate(
        [as_dict(item) for item in items], limit=limit, cursor=query.get("cursor"), resource=resource, query=query
    )
    return Response.json(page)
