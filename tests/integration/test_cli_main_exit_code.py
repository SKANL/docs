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
from docx import Document

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


def test_main_returns_nonzero_when_pipeline_ingest_reports_a_failed_stage(workspace, monkeypatch):
    # Deterministic, environment-independent failure: force pandoc
    # "unavailable" (same technique `test_pipeline_prep_runs_and_reports_a_
    # summary` in test_cli_core.py already uses for `gh`) so a dropped
    # `.docx` source deterministically gets `status: "error"` regardless of
    # whether pandoc happens to be installed on the machine running this
    # test. `stage_ingest` (pipeline.py) already reports `ok=False` for any
    # per-file conversion error, in both strict and non-strict mode -- this
    # test targets ONLY the exit-code propagation bug in `main()`, not that
    # pre-existing pass/fail computation.
    monkeypatch.setattr("shutil.which", lambda name: None)
    Deps().documents.create("doc1", "tesina")
    inbox = workspace / "documents" / "doc1" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # A real minimal .docx (genuine ZIP/docx magic bytes) -- garbage bytes
    # with a `.docx` extension get magic-byte-sniffed as "unsupported"
    # (never even reaching PandocIngestAdapter), which would not trigger
    # the deterministic pandoc-unavailable error this test needs.
    Document().save(str(inbox / "report.docx"))

    for args in (["pipeline", "ingest"], ["pipeline", "ingest", "--strict"]):
        assert main(args) != 0, f"{args} must exit non-zero when a stage reports failure"


def test_main_returns_zero_when_pipeline_ingest_has_nothing_to_fail(workspace):
    Deps().documents.create("doc1", "tesina")
    assert main(["pipeline", "ingest"]) == 0
