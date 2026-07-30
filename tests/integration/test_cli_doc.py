from __future__ import annotations

import json

import pytest
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
    return tmp_path


def test_doc_new_creates_and_activates(ws):
    result = runner.invoke(app, ["doc", "new", "alpha"])
    assert result.exit_code == 0
    assert "creado desde `tesina`" in result.output
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_list_marks_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    out = runner.invoke(app, ["doc", "list"]).output
    assert "* beta" in out and "  alpha" in out


def test_doc_show_prints_document_json(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    payload = json.loads(runner.invoke(app, ["doc", "show"]).output)
    assert payload["id"] == "alpha"


def test_doc_use_switches_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    runner.invoke(app, ["doc", "use", "alpha"])
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_rename(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    result = runner.invoke(app, ["doc", "rename", "alpha", "gamma"])
    assert result.exit_code == 0 and "alpha → gamma" in result.output


def test_doc_delete_requires_yes(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    assert runner.invoke(app, ["doc", "delete", "alpha"]).exit_code == 1
    assert runner.invoke(app, ["doc", "delete", "alpha", "--yes"]).exit_code == 0


def test_doc_list_empty_message(ws):
    result = runner.invoke(app, ["doc", "list"])
    assert "No hay documentos" in result.output


# ── PR2: workspace config + `doc init` bootstrap (design.md item A) ────────


@pytest.fixture
def fresh_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    return tmp_path


def test_doc_init_bootstraps_fresh_workspace(fresh_cwd):
    result = runner.invoke(app, ["doc", "init"])
    assert result.exit_code == 0, result.output

    config = json.loads((fresh_cwd / "docs.config.json").read_text(encoding="utf-8"))
    assert config == {"documents_dir": "documents", "templates_dir": "templates"}
    assert (fresh_cwd / "documents").is_dir()
    assert (fresh_cwd / "templates").is_dir()
    # templates_dir was empty -> seeded with the built-in templates.
    assert (fresh_cwd / "templates" / "documento-generico.json").exists()
    assert (fresh_cwd / "templates" / "reporte-estadia-tic.json").exists()


def test_doc_init_rerun_reports_already_initialized(fresh_cwd):
    runner.invoke(app, ["doc", "init"])
    (fresh_cwd / "documents" / "marker.txt").write_text("keep-me", encoding="utf-8")

    result = runner.invoke(app, ["doc", "init"])

    assert result.exit_code == 0
    assert "ya está inicializado" in result.output
    assert (fresh_cwd / "documents" / "marker.txt").read_text(encoding="utf-8") == "keep-me"


def test_doc_init_refuses_conflicting_config_without_force(fresh_cwd):
    runner.invoke(app, ["doc", "init"])

    result = runner.invoke(app, ["doc", "init", "--documents-dir", "otros-documentos"])

    assert result.exit_code == 1
    config = json.loads((fresh_cwd / "docs.config.json").read_text(encoding="utf-8"))
    assert config["documents_dir"] == "documents"  # unchanged


def test_doc_init_force_overwrites_conflicting_config(fresh_cwd):
    runner.invoke(app, ["doc", "init"])

    result = runner.invoke(app, ["doc", "init", "--documents-dir", "otros-documentos", "--force"])

    assert result.exit_code == 0
    config = json.loads((fresh_cwd / "docs.config.json").read_text(encoding="utf-8"))
    assert config["documents_dir"] == "otros-documentos"
    assert (fresh_cwd / "otros-documentos").is_dir()


def test_doc_init_does_not_reseed_existing_templates(fresh_cwd):
    templates = fresh_cwd / "templates"
    templates.mkdir()
    (templates / "custom.json").write_text('{"type": "custom", "title": "Mine"}', encoding="utf-8")

    result = runner.invoke(app, ["doc", "init"])

    assert result.exit_code == 0
    assert not (templates / "documento-generico.json").exists()
    assert (templates / "custom.json").read_text(encoding="utf-8") == '{"type": "custom", "title": "Mine"}'


# ── PR9: `doc status` resumable summary (design.md item I) ─────────────────

_STATUS_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "context_schema": {"topics": [{"id": "alumno", "title": "Alumno", "required": True, "multiline": True}]},
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": True}],
    "section_contracts": {"introduccion": {}},
}


@pytest.fixture
def status_ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_STATUS_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_doc_status_reports_fresh_document(status_ws):
    runner.invoke(app, ["doc", "new", "alpha"])

    result = runner.invoke(app, ["doc", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["context"] == {"filled": 0, "total": 1, "missing_topics": ["alumno"]}
    assert payload["sections"]["authored"] == 0
    assert payload["sections"]["total"] == 1
    assert payload["sections"]["missing"] == ["introduccion"]
    assert payload["ingest"]["ran"] is False
    assert payload["output"]["draft_exists"] is False


def test_doc_status_markdown_output_mentions_document_id(status_ws):
    runner.invoke(app, ["doc", "new", "alpha"])

    result = runner.invoke(app, ["doc", "status"])

    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "Contexto" in result.output
