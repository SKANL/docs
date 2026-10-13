# src/docs/application/plain_json_writer.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.identity import pretty_json


class PlainJsonWriter:
    """Plain, non-atomic `IngestArtifactWriter`: the default when no writer is injected.

    The composition root injects the atomic `FilesystemIngestArtifactWriter`;
    this one exists so `IngestService`, `GenerateVisualsService` and
    `ContextService` stay usable standalone without `application/` importing
    an `infrastructure/` adapter. Shared here so no module reaches into
    another's private class."""

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self.write_text(path, pretty_json(payload))

    def write_text(self, path: Path, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: Path, data: bytes) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
