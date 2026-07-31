# src/docs/application/inline_json_writer.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class InlineJsonWriter:
    """Default `IngestArtifactWriter` used when the composition root does not
    inject one -- preserves the pre-Front-C constructor ergonomics of the
    services that default to it (dozens of existing unit tests construct them
    with no writer) without any `application/` module importing an
    `infrastructure/` adapter (dependency-direction rule: cli -> application
    -> domain; infrastructure implements domain ports, never the reverse).
    NOT atomic -- the real `FilesystemIngestArtifactWriter` (wired in
    `cli/_shared.py` `Deps.__init__`, design.md Decision 9) is; this fallback
    exists only so `IngestService`/`ContextService` stay usable standalone.
    Shared here (rather than private to `ingest.py`) so `context.py`'s
    gap-report writer does not reach into another module's private class."""

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
