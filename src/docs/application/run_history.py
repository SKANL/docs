from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docs.domain.workspace import Workspace


class RunRecorderService:
    """Persist run records using the legacy on-disk contract."""

    def __init__(self, workspace: Workspace, source_repository: Any) -> None:
        self.workspace = workspace
        self.source_repository = source_repository

    def record(
        self, doc_id: str, config: dict[str, Any], repo_root: Path, command: str, payload: dict[str, Any]
    ) -> Path:
        runs_dir = self._runs_dir(doc_id, config)
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="microseconds")
        record = {
            "timestamp": timestamp,
            "command": command,
            "git_commit": self.source_repository.run_git_rev_parse_head(repo_root),
            **payload,
        }
        path = runs_dir / f"{timestamp.replace(':', '-')}-{command}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        return Path(configured) if configured else self.workspace.doc_root(doc_id) / "runs"


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
