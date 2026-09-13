"""Metadata calculations shared by document-pipeline application services."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.application.output_names import resolve_draft_docx_name
from docs.domain.workspace import Workspace


class PipelineMetadataService:
    """Resolve pipeline metadata without changing pipeline stage behavior."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
        return self.workspace.doc_root(doc_id) / "runs"

    def next_build_version(self, doc_id: str, config: dict[str, Any]) -> int:
        """Return one more than the highest valid build version in the run log."""
        runs_dir = self.runs_dir(doc_id, config)
        if not runs_dir.exists():
            return 1
        latest = 0
        for path in runs_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            version = record.get("build_version")
            if isinstance(version, int) and version > latest:
                latest = version
        return latest + 1

    def resolve_draft_docx_name(self, doc_id: str, config: dict[str, Any]) -> str:
        return resolve_draft_docx_name(doc_id, config)
