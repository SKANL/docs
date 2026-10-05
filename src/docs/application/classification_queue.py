"""Read and confirm the ingest classification queue.

The CLI (`document classify`) and the HTTP API both call this one function so
the queue shapes they accept and the way a role is confirmed cannot diverge.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.application.ingest_names import CLASSIFICATION_QUEUE_NAME

CONFIRMABLE_ROLES = frozenset({"evidence", "example", "normative"})


class ClassificationQueueError(ValueError):
    """The requested confirmation is invalid for the current queue."""


class ClassificationQueueUnavailable(ClassificationQueueError):
    """No classification queue exists yet (ingest has not produced one)."""


def _entries(queue: Any) -> tuple[list[Any], Mapping[str, Any] | None]:
    """Queue entries plus the keyed mapping they came from, if any; corrupt shapes raise."""
    keyed: Mapping[str, Any] | None = None
    if isinstance(queue, list):
        entries = queue
    elif isinstance(queue, Mapping):
        raw = queue.get("entries")
        if isinstance(raw, Mapping):
            keyed, entries = raw, list(raw.values())
        else:
            entries = queue.get("items", queue.get("sources", []))
    else:
        raise ClassificationQueueError("classification queue is corrupt: unexpected top-level value")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ClassificationQueueError("classification queue is corrupt: entries must be objects")
    return entries, keyed


def review_classification_queue(
    document_root: Path,
    relative_path: str | None = None,
    role: str | None = None,
) -> list[dict[str, Any]]:
    """Return the queue entries; confirm `role` for `relative_path` when given."""
    queue_path = Path(document_root) / "inbox" / CLASSIFICATION_QUEUE_NAME
    if not queue_path.is_file():
        raise ClassificationQueueUnavailable("classification queue is unavailable; run document ingest first")
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ClassificationQueueError("classification queue is corrupt: not valid JSON") from exc
    entries, keyed = _entries(queue)
    if relative_path is None and role is None:
        return entries
    if not relative_path or role not in CONFIRMABLE_ROLES:
        raise ClassificationQueueError("--file and --role are required; role must be evidence, example, or normative")
    if isinstance(keyed, Mapping):
        entry = keyed.get(relative_path)
    else:
        entry = next((item for item in entries if str(item.get("relative_path")) == relative_path), None)
    if not isinstance(entry, dict):
        raise ClassificationQueueError("source is not present in the classification queue")
    entry["confirmed_role"] = role
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entries
