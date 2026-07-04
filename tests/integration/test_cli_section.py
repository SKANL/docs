# tests/integration/test_cli_section.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli._shared import Deps
from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina", "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": True}],
    "section_contracts": {"introduccion": {"required_content": ["contexto"]}},
    "context_schema": {"topics": []},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    # `doc new` is Task 6 scope and doesn't exist yet — same deviation as
    # Tasks 1-2 (test_cli_core.py / test_cli_collection.py).
    Deps().documents.create("doc1", "tesina")
    return tmp_path


def test_build_section_writes_scaffold_and_prints_path(ws):
    result = runner.invoke(app, ["build-section", "introduccion"])
    assert result.exit_code == 0
    path = Path(result.output.strip())
    assert path.exists()
    assert "PENDIENTE: documentar contexto con evidencia del ledger, contexto o fuentes." in path.read_text(
        encoding="utf-8"
    )


def test_review_document_exit_1_when_required_section_missing(ws):
    result = runner.invoke(app, ["review-document"])
    assert result.exit_code == 1
    assert "Revisión" in result.output


def test_review_document_json_mode(ws):
    result = runner.invoke(app, ["review-document", "--json"])
    payload = json.loads(result.output)
    assert payload["passed"] is False  # required section absent


def test_review_section_errors_when_section_absent(ws):
    result = runner.invoke(app, ["review-section", "introduccion"])
    assert result.exit_code == 1  # FileNotFoundError -> main() ERROR path


def test_pack_context_document_writes_a_pack(ws):
    result = runner.invoke(app, ["pack-context", "document"])
    assert result.exit_code == 0
    assert Path(result.output.strip()).exists()


def test_pack_context_all_prints_one_line_per_section_plus_document(ws):
    result = runner.invoke(app, ["pack-context", "all"])
    assert result.exit_code == 0
    assert len([ln for ln in result.output.splitlines() if ln.strip()]) == 2  # 1 section + document
