from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.domain.workspace import Workspace


class RunHistoryService:
    """Read the run records stored for a document."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def list_runs(self, doc_id: str, config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        runs_dir = self._runs_dir(doc_id, config)
        if not runs_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return records

    def _runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
        return self.workspace.doc_root(doc_id) / "runs"
