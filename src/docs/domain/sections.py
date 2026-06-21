# src/docs/domain/sections.py
from __future__ import annotations

import json as _json
import re
from pathlib import Path
from typing import Any

_LEADING_ORDER_RE = re.compile(r"^\d+-")


def infer_section_id_from_path(path: Path) -> str:
    return _LEADING_ORDER_RE.sub("", path.stem, count=1)


def with_frontmatter(body: str, metadata: dict[str, Any]) -> str:
    return "---\n" + _json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n---\n" + body


def default_section_metadata(section_id: str, title: str) -> dict[str, Any]:
    return {
        "managed_by": "tesina-harness",
        "schema": 3,
        "section_id": section_id,
        "title": title,
    }


def apply_stamp(
    metadata: dict[str, Any],
    section_id: str,
    title: str,
    body: str,
    body_hash: str,
    authored_by: str,
    model: str,
    stamped_at: str,
) -> dict[str, Any]:
    new_metadata = dict(metadata) if metadata else default_section_metadata(section_id, title)
    new_metadata["authored_by"] = authored_by
    if model:
        new_metadata["model"] = model
    new_metadata["body_hash"] = body_hash
    new_metadata["stamped_at"] = stamped_at
    return new_metadata
