# tests/integration/test_cli_composition_root.py
"""Characterization tests for PR3 (CLI Composition Root Split).

These tests freeze the command surface of the root Typer app BEFORE and
AFTER cli/main.py is split into cli/commands/*_app.py sub-Typer apps, and
assert that:
- the split sub-apps exist and expose the expected commands, and
- the root app's command tree (flat + nested groups) is byte-identical to
  the pre-split surface, and
- the dead root main.py entrypoint is gone.
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.cli.main import app

# Frozen snapshot of the command surface before the split (captured via
# `python -m docs.cli.main --help` and click introspection on main branch
# tip caccb92, after PR2 merged).
_EXPECTED_FLAT_COMMANDS = {
    "doctor", "pipeline", "verify", "history", "stamp",
    "collect-sources", "build-rules", "review-rules", "collect-issues",
    "collect-code-evidence", "build-ledger", "build-section", "pack-context",
    "review-section", "review-document", "build-docx", "qa-docx",
    "format-audit-docx", "apply-corrections", "stamp-section",
}
_EXPECTED_GROUPS = {
    "template": {"list", "show"},
    "doc": {"current", "delete", "list", "new", "rename", "show", "use"},
    "asset": {"add", "list", "rm"},
    "context": {"elicit", "ingest", "rm", "set", "show", "status"},
}


def test_root_app_command_surface_unchanged_after_split():
    click_app = typer.main.get_command(app)
    names = set(click_app.commands.keys())
    assert names == _EXPECTED_FLAT_COMMANDS | set(_EXPECTED_GROUPS)
    for group_name, expected_subcommands in _EXPECTED_GROUPS.items():
        group = click_app.commands[group_name]
        assert set(group.commands.keys()) == expected_subcommands


def test_commands_package_splits_by_concern():
    from docs.cli.commands.core_app import core_app
    from docs.cli.commands.collection_app import collection_app
    from docs.cli.commands.docx_app import docx_app
    from docs.cli.commands.section_app import section_app
    from docs.cli.commands.template_app import template_app
    from docs.cli.commands.doc_app import doc_app
    from docs.cli.commands.asset_app import asset_app
    from docs.cli.commands.context_app import context_app

    def _names(sub_app: typer.Typer) -> set[str]:
        return set(typer.main.get_command(sub_app).commands.keys())

    assert _names(core_app) == {"doctor", "pipeline", "verify", "history", "stamp"}
    assert _names(collection_app) == {
        "collect-sources", "build-rules", "review-rules",
        "collect-issues", "collect-code-evidence", "build-ledger",
    }
    assert _names(docx_app) == {
        "build-docx", "qa-docx", "format-audit-docx",
        "apply-corrections", "stamp-section",
    }
    assert _names(section_app) == {
        "build-section", "pack-context", "review-section", "review-document",
    }
    assert _names(template_app) == {"list", "show"}
    assert _names(doc_app) == {"current", "delete", "list", "new", "rename", "show", "use"}
    assert _names(asset_app) == {"add", "list", "rm"}
    assert _names(context_app) == {"elicit", "ingest", "rm", "set", "show", "status"}


def test_no_dead_root_main_py():
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "main.py").exists()
