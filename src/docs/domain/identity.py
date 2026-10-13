"""Deterministic serialization and SHA-256 identities for domain artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _thaw_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical_json(value: Any, *, strict: bool = False) -> str:
    """Serialize values with the v2 canonical JSON contract.

    Lenient (default): anything unserializable becomes `str(value)`.
    `strict=True`: only JSON values and read-only mappings are accepted; anything else raises
    `TypeError`, and NaN/Infinity raise `ValueError`.
    """
    return json.dumps(
        value,
        default=_thaw_mapping if strict else str,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=not strict,
    )


def sha256_bytes(value: bytes) -> str:
    """Return the SHA-256 digest of raw bytes."""
    return hashlib.sha256(value).hexdigest()


def sha256_content(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON content."""
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file's raw bytes."""
    return sha256_bytes(path.read_bytes())
