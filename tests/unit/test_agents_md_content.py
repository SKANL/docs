# tests/unit/test_agents_md_content.py
"""Agent-contract coverage (spec: agent-contract "Shipped AGENTS.md", MODIFIED
Requirement): AGENTS.md must document the doc revise semantic-edit loop,
output-format selection (docx/html/pdf) including the PDF non-determinism
caveat, and the lifecycle/build-version fields surfaced by `doc status`.
Fast content check on the repo-root file directly (no wheel build) --
tests/unit/test_agents_md_packaging.py already covers the packaged-copy byte
identity separately."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_documents_format_selection_and_pdf_non_determinism_caveat():
    assert "--format" in AGENTS_MD
    assert "html" in AGENTS_MD and "pdf" in AGENTS_MD
    assert "non-byte-deterministic" in AGENTS_MD
    assert "soffice" in AGENTS_MD or "LibreOffice" in AGENTS_MD


def test_documents_doc_revise_loop():
    assert "doc revise" in AGENTS_MD
    assert "revision-log" in AGENTS_MD or "diff" in AGENTS_MD


def test_documents_lifecycle_and_build_version():
    assert "mark-final" in AGENTS_MD
    assert "lifecycle" in AGENTS_MD
    assert "build_version" in AGENTS_MD


def test_documents_second_builtin_template():
    assert "technical-report-srs" in AGENTS_MD


def test_documents_visual_specs_authoring_format():
    assert "visual-specs.json" in AGENTS_MD
    assert "sections/visual-specs.json" in AGENTS_MD
    for field in ("label", "type", "source", "caption"):
        assert field in AGENTS_MD
    assert '"mermaid"' in AGENTS_MD
    assert '"chart"' in AGENTS_MD
    assert "auto-bind" in AGENTS_MD.lower() or "auto-binds" in AGENTS_MD.lower()
    assert "WARN" in AGENTS_MD


# --- drift guard: 4k words of contract vs. the CLI it describes ---------------

import ast
import re

CLI_ROOT = REPO_ROOT / "src" / "docs" / "cli"


def _real_command_surface() -> set[str]:
    """Every invocable command name, flat and grouped (`doc status`, `explain`, ...)."""
    groups: dict[str, str] = {}   # module stem -> mounted group prefix ("" if flat)
    commands: dict[str, list[str]] = {}
    for path in sorted(CLI_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("add_typer"):
                name = next(
                    (k.value.value for k in node.keywords if k.arg == "name"), ""
                )
                target = ast.unparse(node.args[0]) if node.args else ""
                groups[target] = name or ""
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    text = ast.unparse(decorator)
                    if ".command(" not in text:
                        continue
                    app_name = text.split(".command(")[0].lstrip("@")
                    explicit = re.search(r"command\(\s*['\"]([^'\"]+)['\"]", text)
                    commands.setdefault(app_name, []).append(
                        explicit.group(1) if explicit else node.name.replace("_", "-")
                    )
    surface = set()
    for app_name, names in commands.items():
        prefix = groups.get(app_name, "")
        for name in names:
            surface.add(f"{prefix} {name}".strip())
    return surface


def _commands_mentioned_in_agents_md() -> set[str]:
    """`docs <cmd>` / `docs <group> <sub>` occurrences, code spans included."""
    real = _real_command_surface()
    mentioned = set()
    for match in re.finditer(r"\bdocs\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?", AGENTS_MD):
        first, second = match.group(1), match.group(2)
        two_word = f"{first} {second}" if second else None
        if two_word and two_word in real:
            mentioned.add(two_word)
        elif first in real:
            mentioned.add(first)
        elif two_word or first:
            # Unknown either way -- record the most specific reading so the
            # assertion below can report exactly what AGENTS.md claims.
            mentioned.add(two_word or first)
    return mentioned


def test_the_command_scan_finds_the_real_surface():
    surface = _real_command_surface()
    assert {"explain", "doc status", "review-section", "pipeline"} <= surface, surface


def test_agents_md_never_documents_a_command_that_does_not_exist():
    # The direction that actually rots: the CLI changes and 4k words of
    # contract keep describing the old surface. 5 tests and 17 asserts used
    # to guard this whole file; none of them compared it to the CLI.
    real = _real_command_surface()
    ghosts = sorted(name for name in _commands_mentioned_in_agents_md() if name not in real)
    assert not ghosts, (
        f"AGENTS.md documenta comandos que no existen: {ghosts}. "
        f"O se renombraron en el CLI y el contrato quedó viejo, o son una "
        f"invención. Superficie real: {sorted(real)}"
    )


def test_agents_md_points_at_docs_explain_for_issue_codes():
    # The review loop (§4) is the harness's core contract with the agent; it
    # emits 31 codes and must route to the catalog rather than restate it.
    assert "docs explain" in AGENTS_MD


def test_the_determinism_promise_is_scoped_to_a_toolchain():
    # It used to read "byte-identical output, every time, on every machine",
    # unqualified. The harness pipes Markdown through pandoc, and pandoc 3.1.3
    # and 3.10 do not emit the same bytes -- a fact the first CI run made
    # concrete. A contract that promises more than the system can deliver
    # sends the next person hunting a harness bug that is really an upgrade.
    #
    # Whitespace-normalised: the claim must survive a markdown re-wrap, and
    # asserting on an exact line break would fail on formatting, not on
    # meaning.
    prose = " ".join(AGENTS_MD.split())
    assert "not across toolchain versions" in prose
    assert "docs doctor" in prose
