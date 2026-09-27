from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.cli._shared import build_workspace
from docs.domain.workspace_format import WorkspaceFormatError, write_workspace_marker


def _canonical_workspace(root: Path) -> None:
    write_workspace_marker(root)


def test_build_workspace_config_file_overrides_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _canonical_workspace(tmp_path)
    config = {"documents_dir": "cfg-documents", "templates_dir": "cfg-templates"}
    (tmp_path / "docs.config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", "env-documents")
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")

    ws = build_workspace()

    assert ws.documents_dir == tmp_path / "cfg-documents"
    assert ws.templates_dir == tmp_path / "cfg-templates"


def test_build_workspace_env_used_when_no_config_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _canonical_workspace(tmp_path)
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", "env-documents")
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")

    ws = build_workspace()

    assert ws.documents_dir == tmp_path / "env-documents"
    assert ws.templates_dir == tmp_path / "env-templates"


def test_build_workspace_default_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _canonical_workspace(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    # Isolate the persistent X20 workspace registry from the developer's
    # selected workspace; this test exercises cwd-relative defaults.
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "registry.json"))

    ws = build_workspace()

    assert ws.documents_dir == tmp_path / "documents"
    assert ws.templates_dir == tmp_path / "templates"


def test_build_workspace_malformed_config_warns_and_falls_back(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _canonical_workspace(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", "env-templates")
    (tmp_path / "docs.config.json").write_text("{not valid json", encoding="utf-8")

    ws = build_workspace()

    # Never bricked: falls back to env/default despite the malformed file.
    assert ws.documents_dir == tmp_path / "documents"
    assert ws.templates_dir == tmp_path / "env-templates"
    assert "docs.config.json" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("config", "env"),
    [
        ({"documents_dir": "cfg-documents", "templates_dir": "cfg-templates"}, {}),
        (None, {"DOCS_DOCUMENTS_DIR": "env-documents", "DOCS_TEMPLATES_DIR": "env-templates"}),
        (None, {}),
    ],
    ids=("config", "environment", "default"),
)
def test_build_workspace_rejects_unmarked_roots_without_mutation(tmp_path, monkeypatch, config, env):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCS_DOCUMENTS_DIR", raising=False)
    monkeypatch.delenv("DOCS_TEMPLATES_DIR", raising=False)
    monkeypatch.setenv("DOCS_WORKSPACE_REGISTRY", str(tmp_path / "registry.json"))
    if config is not None:
        (tmp_path / "docs.config.json").write_text(json.dumps(config), encoding="utf-8")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(WorkspaceFormatError, match="workspace_marker_missing"):
        build_workspace()

    assert sorted(path.name for path in tmp_path.iterdir()) == (["docs.config.json"] if config else [])
