from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
PROJECT_ROOT = SRC_ROOT.parents[1]
_PLUGIN_IMPORT = re.compile(r"(?:^|\\.)plugins?(?:\\.|$)", re.IGNORECASE)
_PLUGIN_DEPENDENCY = re.compile(r"(?:^|[-_])plugin(?:[-_]|$)", re.IGNORECASE)


def test_v2_runtime_has_no_plugin_imports_or_plugin_dependencies() -> None:
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _PLUGIN_IMPORT.search(alias.name):
                        violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and _PLUGIN_IMPORT.search(node.module):
                violations.append(f"{path.relative_to(PROJECT_ROOT)} imports {node.module}")
    project = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in project.splitlines():
        dependency = line.strip().strip('"').strip("'")
        if dependency and not dependency.startswith("#") and _PLUGIN_DEPENDENCY.search(dependency):
            violations.append(f"pyproject.toml declares {dependency}")
    assert not violations, "v2 must remain plugin-independent:\n" + "\n".join(violations)
