# tests/unit/cli/test_command_help_coverage.py
"""Every CLI command must describe itself.

The only consumer of this harness is an agent, and an agent that cannot
learn a command from `--help` has to load the whole 4k-word `AGENTS.md`
into context to discover that `pack-context` exists. 38 of 46 commands
shipped with no help text at all -- not by decision, but because the Slice
15 port from the legacy monolith preserved exit codes byte-for-byte and the
monolith had no help either. Nothing failed, so nobody noticed.

This is the check that would have noticed.
"""
from __future__ import annotations

import ast
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[3] / "src" / "docs" / "cli"


def _commands() -> list[tuple[str, str, bool]]:
    """(module, function, documented) for every `@*.command()`-decorated def."""
    found = []
    for path in sorted(CLI_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any(".command(" in d for d in decorators):
                continue
            documented = ast.get_docstring(node) is not None or any("help=" in d for d in decorators)
            found.append((path.name, node.name, documented))
    return found


def test_the_scan_finds_the_cli_command_surface():
    # Guards against a vacuous pass: an AST walk that silently stops matching
    # (a decorator rename, a moved package) would otherwise report "0 of 0
    # commands undocumented" and look green forever.
    assert len(_commands()) >= 40


def test_every_command_has_help_text():
    # A plain assert, not an empty `parametrize`: the latter reports SKIPPED
    # when the list is empty, so the healthy state would be indistinguishable
    # from a collection that stopped finding anything.
    undocumented = [f"{module}:{name}" for module, name, documented in _commands() if not documented]
    assert not undocumented, (
        f"{len(undocumented)} comandos sin docstring ni `help=`: {undocumented}. "
        f"Typer no puede mostrarlos en `--help`, y el agente que maneja el "
        f"arnés no puede descubrirlos sin leer AGENTS.md entero."
    )


def test_help_text_is_a_description_not_a_restated_name():
    # A docstring that only echoes the command name teaches nothing and would
    # pass the check above. Requiring a real sentence keeps the guard honest.
    thin = []
    for path in sorted(CLI_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(".command(" in ast.unparse(d) for d in node.decorator_list):
                continue
            doc = ast.get_docstring(node)
            if doc is None:
                continue
            first_line = doc.strip().split("\n")[0]
            if len(first_line.split()) < 4:
                thin.append(f"{path.name}:{node.name} -> {first_line!r}")
    assert not thin, f"help demasiado escueto para ser útil: {thin}"
