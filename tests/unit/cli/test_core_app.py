# tests/unit/cli/test_core_app.py
"""`docs guide` (design.md item B: agent contract, Task 10.4). No workspace
fixture needed -- the guide is static content, not document-scoped."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_guide_prints_the_full_agents_md_content():
    result = runner.invoke(app, ["guide"])
    assert result.exit_code == 0
    repo_root_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert result.output.strip() == repo_root_text.strip()


def test_guide_documents_the_end_to_end_workflow_commands():
    result = runner.invoke(app, ["guide"])
    for command in ("pipeline ingest", "review-section", "pipeline assemble", "docs.config.json"):
        assert command in result.output
