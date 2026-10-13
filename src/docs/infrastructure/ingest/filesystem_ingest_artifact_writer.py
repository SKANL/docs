# src/docs/infrastructure/ingest/filesystem_ingest_artifact_writer.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.identity import pretty_json
from docs.infrastructure.atomic_write import atomic_write_bytes, atomic_write_text


class FilesystemIngestArtifactWriter:
    """`IngestArtifactWriter` implementation: atomic, deterministic writer for every
    ingest-produced artifact (design.md Decision 9). Every write is temp-then-rename in
    the destination's own directory via `infrastructure/atomic_write.py`, so a failing or
    interrupted write never leaves a partial artifact at `path`."""

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        atomic_write_text(path, pretty_json(payload))

    def write_text(self, path: Path, text: str) -> None:
        atomic_write_text(path, text)

    def write_bytes(self, path: Path, data: bytes) -> None:
        atomic_write_bytes(path, data)
