from __future__ import annotations

import json

from docs.application.run_history import RunHistoryService
from docs.domain.workspace import Workspace


def test_list_runs_returns_recent_records_from_document_runs_directory(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    runs_dir = workspace.doc_root("doc1") / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "2024-01-02T00-00-00-000002-verify.json").write_text(
        json.dumps({"timestamp": "later"}), encoding="utf-8"
    )
    (runs_dir / "2024-01-01T00-00-00-000001-verify.json").write_text(
        json.dumps({"timestamp": "earlier"}), encoding="utf-8"
    )

    records = RunHistoryService(workspace).list_runs("doc1", {"paths": {}})

    assert [record["timestamp"] for record in records] == ["later", "earlier"]
