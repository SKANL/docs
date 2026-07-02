# tests/integration/test_cli_docx.py
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
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
    "section_contracts": {}, "context_schema": {"topics": []},
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
    # Tasks 1-3 (test_cli_core.py / test_cli_collection.py / test_cli_section.py).
    Deps().documents.create("doc1", "tesina")
    return tmp_path


def test_apply_corrections_reports_zero_when_inbox_empty(ws):
    result = runner.invoke(app, ["apply-corrections"])
    assert result.exit_code == 0
    assert "Correcciones aplicadas: 0" in result.output


def test_build_docx_errors_cleanly_without_sections(ws):
    result = runner.invoke(app, ["build-docx"])
    assert result.exit_code == 1  # RuntimeError (no sections / no pandoc) -> ERROR path


def test_format_audit_docx_errors_when_docx_missing(ws):
    result = runner.invoke(app, ["format-audit-docx", str(ws / "missing.docx")])
    assert result.exit_code == 1  # FileNotFoundError -> ERROR path


def test_qa_docx_errors_when_docx_missing(ws):
    result = runner.invoke(app, ["qa-docx", str(ws / "missing.docx")])
    assert result.exit_code == 1


def test_stamp_section_errors_when_section_absent(ws):
    result = runner.invoke(app, ["stamp-section", "introduccion", "--by", "gpt"])
    assert result.exit_code == 1  # FileNotFoundError: section not written yet
