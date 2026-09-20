"""Attribute hygiene for observability signals."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from docs.domain.evidence_passport import redact

# These are deliberately bounded to prevent IDs, paths, payloads, and other
# accidental high-cardinality values from becoming metric dimensions.
_LOW_CARDINALITY_KEYS = frozenset(
    {
        "component",
        "format",
        "kind",
        "mode",
        "operation",
        "outcome",
        "pipeline",
        "reason",
        "source",
        "stage",
        "status",
        "error_type",
    }
)

_SAFE_VALUES = {
    "format": frozenset({"docx", "html", "pdf", "json", "markdown"}),
    "kind": frozenset({"input", "output", "source", "artifact"}),
    "mode": frozenset({"default", "draft", "final", "strict"}),
    "outcome": frozenset({"failed", "skipped", "succeeded", "unsupported"}),
    "source": frozenset({"external", "filesystem", "generated", "ingested"}),
    "status": frozenset({"accepted", "failed", "ok", "pending", "rejected"}),
    "stage": frozenset(
        {
            "build-docx",
            "build-html",
            "build-pdf",
            "ingest",
            "package-release",
            "prepare",
            "publish-draft",
            "verify",
        }
    ),
}
_SAFE_NUMERIC_LIMIT = 1_000_000
_MAX_SIGNAL_TEXT = 256


def redact_text(value: str, *, limit: int = _MAX_SIGNAL_TEXT) -> str:
    """Redact sensitive content and cap free-form telemetry text."""
    return str(redact(value))[:limit]


def redact_signal_name(value: str) -> str:
    """Return a bounded metric/span name without free-form content."""
    redacted = redact_text(value)
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "_", redacted)
    return normalized[:_MAX_SIGNAL_TEXT] or "docs.telemetry"


def redact_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return safe, bounded signal attributes.

    Unknown keys are discarded rather than guessed safe. Values are recursively
    redacted before only scalar values are retained.
    """
    if not attributes:
        return {}
    safe = redact(dict(attributes))
    bounded: dict[str, Any] = {}
    for key, value in safe.items():
        if key not in _LOW_CARDINALITY_KEYS:
            continue
        if isinstance(value, str):
            if value not in _SAFE_VALUES.get(key, frozenset()):
                continue
        elif type(value) in {int, float}:
            if not math.isfinite(float(value)) or abs(float(value)) > _SAFE_NUMERIC_LIMIT:
                continue
        elif type(value) is not bool:
            continue
        bounded[key] = value
    return bounded
