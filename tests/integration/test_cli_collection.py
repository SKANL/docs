# tests/integration/test_cli_collection.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli._shared import Deps
from docs.cli.main import app

runner = CliRunner()

@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    # DEVIATION from the plan's literal `_TEMPLATE` (a module-level constant
    # with no "paths" key): EvidenceService.build_rules reads
    # config["paths"]["manual_dir"]/["extracted_dir"] as *required* keys
    # (evidence.py:35-36, KeyError if absent) — confirmed against
    # test_evidence_service.py's own fixture, which always supplies both.
    # _computed_paths() (Judgment call 2) does not compute these two paths;
    # they must come from the template. Neither directory needs to exist:
    # list_manual_files() globs a nonexistent dir cleanly (empty result) and
    # extracted_dir is existence-checked before listing (evidence.py:70).
    template = {
        "type": "tesina", "title": "Tesina",
        "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
        "section_contracts": {},
        "context_schema": {"topics": []},
        "paths": {
            "manual_dir": str(tmp_path / "manual"),
            "extracted_dir": str(tmp_path / "extracted"),
        },
    }
    (templates / "tesina.json").write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    # DEVIATION from the plan's literal fixture (which invokes `docs doc new`):
    # the `doc` command group is Task 6's scope and does not exist yet. Same
    # deviation established in Task 1's test_cli_core.py.
    Deps().documents.create("doc1", "tesina")
    return tmp_path


def test_collect_sources_prints_manifest_path(ws):
    result = runner.invoke(app, ["collect-sources"])
    assert result.exit_code == 0
    assert result.output.strip().endswith("source-manifest.json")
    assert Path(result.output.strip()).exists()


def test_build_rules_prints_manifest_path(ws):
    result = runner.invoke(app, ["build-rules"])
    assert result.exit_code == 0
    assert Path(result.output.strip()).exists()


def test_review_rules_exit_1_when_manifest_missing_under_strict(ws):
    result = runner.invoke(app, ["review-rules", "--strict"])
    assert result.exit_code == 1
    assert "Revisión" in result.output


def test_review_rules_json_mode(ws):
    result = runner.invoke(app, ["review-rules", "--json"])
    payload = json.loads(result.output)
    assert "passed" in payload and "issues" in payload


def test_collect_issues_errors_cleanly_without_gh(ws, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = runner.invoke(app, ["collect-issues"])
    assert result.exit_code == 1  # RuntimeError -> main() ERROR path


def test_build_ledger_writes_and_prints_path(ws):
    result = runner.invoke(app, ["build-ledger"])
    assert result.exit_code == 0
    ledger = Path(result.output.strip())
    assert ledger.exists() and ledger.read_text(encoding="utf-8").startswith("# Fact Ledger")
