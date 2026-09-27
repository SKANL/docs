"""Guard the v2 runtime against deleted alternate pipeline adapters."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_current_pipeline_adapters_are_not_runtime_modules() -> None:
    forbidden = (
        ROOT / "src" / "docs" / "application" / "current_pipeline.py",
        ROOT / "src" / "docs" / "cli" / "current_pipeline_bridge.py",
        ROOT / "src" / "docs" / "application" / "current_pipeline_executor.py",
    )
    assert all(not path.exists() for path in forbidden)


def test_obsolete_x20_facades_are_not_runtime_modules() -> None:
    forbidden = (
        ROOT / "src" / "docs" / "domain" / "ports" / "x20.py",
        ROOT / "src" / "docs" / "infrastructure" / "persistence" / "x20.py",
        ROOT / "src" / "docs" / "infrastructure" / "persistence" / f"sqlite_{'x20'}.py",
    )
    assert all(not path.exists() for path in forbidden)


def test_runtime_imports_use_semantic_modules_not_obsolete_x20_facades() -> None:
    legacy_modules = {
        f"docs.domain.ports.{'x20'}",
        f"docs.infrastructure.persistence.{'x20'}",
        f"docs.infrastructure.persistence.sqlite_{'x20'}",
    }
    source_files = (*ROOT.glob("src/**/*.py"), *ROOT.glob("tests/**/*.py"))
    imported_modules = {
        node.module
        for path in source_files
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert legacy_modules.isdisjoint(imported_modules)
