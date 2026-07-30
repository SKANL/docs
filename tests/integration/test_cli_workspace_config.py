from __future__ import annotations

import json
from pathlib import Path

from docs.cli._shared import build_workspace


def test_build_workspace_config_file_overrides_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {"documents_dir": "cfg-documents", "templates_dir": "cfg-templates"}
    (tmp_path / "docs.config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", "env-documents")
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")
    ws = build_workspace()
    assert ws.documents_dir == Path("cfg-documents")
    assert ws.templates_dir == Path("cfg-templates")


def test_build_workspace_env_used_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", "env-documents")
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")
    ws = build_workspace()
    assert ws.documents_dir == Path("env-documents")
    assert ws.templates_dir == Path("env-templates")


def test_build_workspace_default_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    ws = build_workspace()
    assert ws.documents_dir == Path("documents")
    assert ws.templates_dir == Path("templates")


def test_build_workspace_malformed_config_warns_and_falls_back(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")
    (tmp_path / "docs.config.json").write_text("{not valid json", encoding="utf-8")
    ws = build_workspace()
    # Never bricked: falls back to env/default despite the malformed file.
    assert ws.documents_dir == Path("documents")
    assert ws.templates_dir == Path("env-templates")
    assert "docs.config.json" in capsys.readouterr().err
