# tests/architecture/test_ports_have_consumers.py
"""A domain port earns its place only when the application layer depends on it.

A port exists so application code can name a collaborator without importing
infrastructure. One that only an infrastructure adapter imports is ceremony:
the adapter could name its sibling directly. An AST scan needs no graph index,
so it never skips.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
PORTS = SRC_ROOT / "domain" / "ports"

# Runtime-store ports whose conformance is pinned by `test_runtime_ports.py`
# and whose stores reach the API through untyped slots. Pruning them is a
# separate decision from the one-impl/zero-fake candidates; shrink-only.
KNOWN_ORPHANS = {"blob_store", "graph_store", "plugin_executor"}


def _imported_port_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("docs.domain.ports."):
                modules.add(node.module.rsplit(".", 1)[1])
            elif node.module == "docs.domain.ports":
                modules.update(alias.name for alias in node.names)
    return modules


def _consumers() -> set[str]:
    used: set[str] = set()
    for path in SRC_ROOT.rglob("*.py"):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative.startswith(("infrastructure/", "domain/ports/")):
            continue
        used |= _imported_port_modules(path)
    return used


def test_the_scan_sees_a_real_consumer():
    assert "section_repository" in _consumers()


def test_every_port_has_a_consumer_outside_infrastructure():
    ports = {path.stem for path in PORTS.glob("*.py") if path.stem != "__init__"}
    orphans = sorted(ports - _consumers() - KNOWN_ORPHANS)
    assert not orphans, (
        f"estos puertos solo los usa infraestructura: {orphans}. "
        "Un puerto sin consumidor en application/ es ceremonia: borralo."
    )


def test_the_orphan_allowlist_only_shrinks():
    stale = sorted(KNOWN_ORPHANS & _consumers())
    assert not stale, f"ya tienen consumidor; quitalos de KNOWN_ORPHANS: {stale}"
