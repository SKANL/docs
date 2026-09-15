# tests/integration/test_cli_main_exit_code.py
"""MEDIUM contract-violation fix: `docs.cli.main.main()` (the real
`docs = "docs.cli.main:main"` console-script entrypoint declared in
pyproject.toml) discarded `app(args=..., standalone_mode=False)`'s return
value. With `standalone_mode=False`, Click never re-raises `typer.Exit` --
it swallows it internally and returns `exit_code` as the call's return
value instead -- so every command signaling failure via
`raise typer.Exit(code=1)` (pipeline, doctor, docx/section build, ...)
silently exited 0 through the real entrypoint, even though the SAME failure
correctly produces a non-zero `result.exit_code` through
`typer.testing.CliRunner` (which every other CLI integration test in this
suite uses -- exactly why this went unnoticed). AGENTS.md §1 documents
`--strict` as "restoring hard-fail for CI"; this is the bug that broke it,
for every command, not just `pipeline ingest`."""
from __future__ import annotations

import json

import pytest

from docs.cli._shared import Deps
from docs.cli.main import main

_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": False}],
    "section_contracts": {"introduccion": {}},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    templates = tmp_path / "templates"
    documents.mkdir()
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_main_returns_zero_for_a_successful_command(workspace):
    # Sanity check: a command that never raises `typer.Exit` (this bug's
    # fix normalizes `app(...)`'s `None` return to 0) must stay 0.
    assert main(["stamp"]) == 0






def test_main_propagates_a_nonzero_nonone_exit_code(workspace, monkeypatch):
    # The fix must propagate an ARBITRARY exit code, not only 0/1 -- guards
    # against a future regression that special-cases 1. `doctor` raises
    # `typer.Exit(code=2)` when a required check fails (core_app.py). Under
    # `--strict` the `gh` check becomes required (doctor.py); forcing
    # `shutil.which` to None (same deterministic, environment-independent
    # technique as the pandoc test above) makes gh unavailable -> required
    # failure -> `result.passed` False -> exit 2 through the real entrypoint.
    # Closes the review coverage gap where only codes 0 and 1 were exercised
    # via main() -- the exact blind spot (CliRunner-only) that hid the bug.
    monkeypatch.setattr("shutil.which", lambda name: None)
    Deps().documents.create("doc1", "tesina")
    assert main(["doctor", "--strict"]) == 2
