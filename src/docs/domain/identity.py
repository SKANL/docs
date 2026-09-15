"""Deterministic serialization and SHA-256 identities for domain artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize values with the v2 canonical JSON contract."""
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    """Return the SHA-256 digest of raw bytes."""
    return hashlib.sha256(value).hexdigest()


def sha256_content(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON content."""
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file's raw bytes."""
    return sha256_bytes(path.read_bytes())
