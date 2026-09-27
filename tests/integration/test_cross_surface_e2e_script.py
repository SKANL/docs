from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from docs.domain.contracts import Run
from docs.infrastructure.persistence.sqlite_runtime import SqliteRunStore

SCRIPTS = Path(__file__).resolve().parents[2] / "desktop" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_cross_surface_e2e import (
    assert_same_persisted_records,
    run_cli_json,
)


def test_cli_reads_the_same_persisted_document_and_run_records(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "docs.cli.main", "doc", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "-m", "docs.cli.main", "doc", "new", "cross-surface", "--template", "documento-generico"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    run = Run(
        "run-cross-surface",
        "queued",
        {"workspace_id": "local", "document_id": "cross-surface", "format": "docx"},
        "2026-01-01T00:00:00+00:00",
    )
    SqliteRunStore(tmp_path / ".docs" / "x20.sqlite3").put(run)

    document = json.loads((tmp_path / "documents" / "cross-surface" / "document.json").read_text(encoding="utf-8"))
    cli_document = json.loads(run_cli_json(tmp_path, "doc", "show", "cross-surface"))
    cli_runs = json.loads(run_cli_json(tmp_path, "run", "list", "--json"))
    cli_run = next(item for item in cli_runs if item["id"] == run.id)

    assert_same_persisted_records(
        {"id": "cross-surface", **document},
        cli_document,
        run.to_dict(),
        cli_run,
    )


def test_same_record_assertion_reports_cross_surface_drift() -> None:
    with pytest.raises(AssertionError, match="document id mismatch"):
        assert_same_persisted_records(
            {"id": "api-document"},
            {"id": "cli-document"},
            {"id": "run", "status": "queued", "payload": {}},
            {"id": "run", "status": "queued", "payload": {}},
        )
