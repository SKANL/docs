"""Passport-derived, low-cardinality measurements."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from docs.domain.contracts import Passport

_KNOWN_STATUSES = frozenset({"accepted", "failed", "pending", "rejected", "skipped"})


def passport_metrics(passport: Passport) -> dict[str, int]:
    """Derive aggregate passport metrics without exposing run or artifact IDs."""
    statuses = Counter(
        entry.get("status") if entry.get("status") in _KNOWN_STATUSES else "other"
        for entry in passport.entries
        if isinstance(entry.get("status"), str)
    )
    kinds = {entry.get("kind") for entry in passport.entries if isinstance(entry.get("kind"), str)}
    metrics = {"passport.entries": len(passport.entries), "passport.kinds": len(kinds)}
    for status, count in sorted(statuses.items()):
        metrics[f"passport.entries.{status}"] = count
    return metrics


def passport_metric_attributes(entry: Mapping[str, Any]) -> dict[str, str]:
    """Return the small bounded attribute subset useful for a single entry."""
    return {key: value for key in ("kind", "status") if isinstance(value := entry.get(key), str)}
