from __future__ import annotations

import json

import pytest
from docx import Document as DocxDocument
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def _make_docx(tmp_path, name="cover.docx"):
    path = tmp_path / name
    DocxDocument().save(path)
    return path


def test_asset_list_empty_message(ws):
    result = runner.invoke(app, ["asset", "list"])
    assert result.exit_code == 0
    assert "No hay assets" in result.output


def test_asset_add_then_list(ws):
    src = _make_docx(ws)
    add = runner.invoke(app, ["asset", "add", str(src), "--name", "portada"])
    assert add.exit_code == 0 and "agregado" in add.output
    listed = runner.invoke(app, ["asset", "list"]).output
    assert "- portada" in listed


def test_asset_add_rejects_non_docx(ws):
    bad = ws / "notes.txt"
    bad.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["asset", "add", str(bad)])
    assert result.exit_code == 1  # ValueError -> ERROR path


def test_asset_rm(ws):
    src = _make_docx(ws)
    runner.invoke(app, ["asset", "add", str(src), "--name", "portada"])
    result = runner.invoke(app, ["asset", "rm", "portada"])
    assert result.exit_code == 0 and "eliminado" in result.output
    assert "No hay assets" in runner.invoke(app, ["asset", "list"]).output
