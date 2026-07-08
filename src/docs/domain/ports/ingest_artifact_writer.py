# src/docs/domain/ports/ingest_artifact_writer.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class IngestArtifactWriter(Protocol):
    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        """Write `payload` to `path` as deterministic JSON -- stable key
        ordering (`sort_keys`), no timestamps or randomness -- via an
        ATOMIC temp-then-rename so a failing or interrupted write never
        leaves a corrupt or partial artifact at `path` (design.md Decision
        9: every ingest-produced artifact -- detection report, source
        manifest, and later the classification/placement queues -- shares
        this one seam)."""
        ...
