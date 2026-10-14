"""Config, token and path resolution that used to live in the composition root."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application import workspace_config as wc
from docs.domain.workspace import Workspace


def test_deep_merge_nests_dicts_and_lets_non_null_overrides_win() -> None:
    merged = wc.deep_merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}, "b": None, "c": 4})
    assert merged == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}


def test_expand_tokens_reaches_nested_values_and_leaves_unknown_tokens_literal() -> None:
    expanded = wc.expand_tokens({"p": ["{cwd}/a", {"q": "{nope}"}], "n": 3}, {"{cwd}": "/w"})
    assert expanded == {"p": ["/w/a", {"q": "{nope}"}], "n": 3}


def test_standard_tokens_and_computed_paths_are_absolute_and_per_document(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path, documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    doc_root = tmp_path / "documents" / "d1"
    tokens = wc.standard_tokens(workspace, doc_root)
    assert tokens["{inbox_dir}"] == str((doc_root / "inbox").resolve())
    paths = wc.computed_paths(doc_root)
    assert paths["sections_dir"] == str(doc_root.resolve() / "sections")
    assert Path(paths["output_draft_dir"]).is_absolute()


def test_load_workspace_config_ignores_a_malformed_file_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert wc.load_workspace_config() is None
    (tmp_path / wc.WORKSPACE_CONFIG_FILENAME).write_text("{", encoding="utf-8")
    assert wc.load_workspace_config() is None
    assert "WARN" in capsys.readouterr().err
    (tmp_path / wc.WORKSPACE_CONFIG_FILENAME).write_text(json.dumps({"documents_dir": "d"}), encoding="utf-8")
    assert wc.load_workspace_config() == {"documents_dir": "d"}


def test_confirmed_cover_replaces_the_template_cover(tmp_path: Path) -> None:
    from docs.application.ingest import SOURCE_MANIFEST_NAME

    (tmp_path / SOURCE_MANIFEST_NAME).write_text(
        json.dumps({"placements": [{"structure_part": {"type": "cover_from_asset"}}, {}]}), encoding="utf-8"
    )
    parts = [{"type": "cover_from_template"}, {"type": "sections"}]
    assert wc.apply_confirmed_placements(parts, tmp_path) == [{"type": "cover_from_asset"}, {"type": "sections"}]
    assert wc.apply_confirmed_placements(parts, tmp_path / "missing") is parts


def test_try_compile_template_warns_and_returns_none_when_the_template_does_not_compile(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from docs.template_compiler import TemplateCompilationError

    def refuse(_template: object) -> None:
        raise TemplateCompilationError("broken contract")

    monkeypatch.setattr(wc, "compile_template", refuse)

    with caplog.at_level("WARNING", logger=wc.logger.name):
        assert wc.try_compile_template(object()) is None  # type: ignore[arg-type]

    assert "template IR unavailable" in caplog.text


def test_rules_manifest_state_reports_presence_and_size(tmp_path: Path) -> None:
    manifest = tmp_path / "rules.json"
    assert wc.rules_manifest_state({"paths": {"rules_manifest": str(manifest)}}) == (False, 0)
    manifest.write_text("abc", encoding="utf-8")
    assert wc.rules_manifest_state({"paths": {"rules_manifest": str(manifest)}}) == (True, 3)
    assert wc.rules_manifest_state({}) == (False, 0)
