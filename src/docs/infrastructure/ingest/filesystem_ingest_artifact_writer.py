# src/docs/infrastructure/ingest/filesystem_ingest_artifact_writer.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class FilesystemIngestArtifactWriter:
    """`IngestArtifactWriter` implementation: atomic, deterministic JSON
    writer for every ingest-produced artifact (design.md Decision 9).
    Writes to a temp file created INSIDE `path`'s own parent directory (same
    filesystem, so `os.replace` below is a true atomic rename, not a
    cross-device copy) and only replaces `path` on success -- mirrors the
    temp-then-atomic-rename convention `infrastructure/ingest/
    atomic_ingest_write.py` already establishes for ingest OUTPUT files,
    applied here to ingest ARTIFACTS (reports/manifests/queues)."""

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".ingest-artifact-tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
