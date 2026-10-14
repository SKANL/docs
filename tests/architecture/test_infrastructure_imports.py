# tests/architecture/test_infrastructure_imports.py
"""Only `composition.py` (and `infrastructure/` itself) may import infrastructure.

`cli -> application -> domain` with adapters implementing domain ports only
holds if the single composition root is the one place that names concrete
adapters. A module that imports `docs.infrastructure` directly builds its own
wiring, which is how the same SQLite path and registry lookup ended up
duplicated across cli, sidecar and workers.

An AST scan needs no graph index, so it never skips. It sees `import`,
`from ... import` (relative too) and `import_module("docs.infrastructure...")`
with a literal string.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
_FORBIDDEN = "docs.infrastructure"
_ALLOWED_ROOTS = ("infrastructure/", "composition.py")

# Named, justified and shrink-only: a listed module that stops violating fails
# the test so the entry gets deleted.
KNOWN_EXCEPTIONS = {
    # Subclasses the concrete ledger through a lazy `import_module` so that
    # ten application services can keep calling `ProvenanceLedger(...)`.
    # Removing it needs a provenance port plus injection through the root.
    "application/provenance.py",
}


def _is_infra(name: str) -> bool:
    return name == _FORBIDDEN or name.startswith(_FORBIDDEN + ".")


def _imports_infrastructure(tree: ast.AST, relative: str) -> bool:
    package = ["docs", *relative.split("/")[:-1]]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_infra(a.name) for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join([*base, *([module] if module else [])])
            if _is_infra(module):
                return True
            if module == "docs" and any(a.name == "infrastructure" for a in node.names):
                return True
        elif isinstance(node, ast.Call) and node.args:
            first = node.args[0]
            if (
                ast.unparse(node.func).endswith("import_module")
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and _is_infra(first.value)
            ):
                return True
    return False


def _violators(root: Path = SRC_ROOT) -> set[str]:
    found = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(_ALLOWED_ROOTS[0]) or relative == _ALLOWED_ROOTS[1]:
            continue
        if _imports_infrastructure(ast.parse(path.read_text(encoding="utf-8")), relative):
            found.add(relative)
    return found


def test_the_scan_sees_every_import_shape():
    # Vacuous-pass guard: each shape must be detected, or "0 violators" means
    # nothing.
    shapes = {
        "cli/a.py": "import docs.infrastructure.locking\n",
        "cli/b.py": "from docs.infrastructure.locking import x\n",
        "cli/c.py": "from ..infrastructure.locking import x\n",
        "b.py": "from .infrastructure.locking import x\n",
        "cli/d.py": "from docs import infrastructure\n",
        "cli/e.py": "import_module('docs.infrastructure.provenance.ledger')\n",
    }
    for relative, source in shapes.items():
        assert _imports_infrastructure(ast.parse(source), relative), relative
    assert not _imports_infrastructure(ast.parse("from docs.domain import x\n"), "cli/f.py")


def test_the_scan_finds_a_real_infrastructure_import():
    composition = SRC_ROOT / "composition.py"
    assert _imports_infrastructure(ast.parse(composition.read_text(encoding="utf-8")), "composition.py")


def test_only_the_composition_root_imports_infrastructure():
    new = sorted(_violators() - KNOWN_EXCEPTIONS)
    assert not new, (
        f"estos módulos importan `docs.infrastructure` directamente: {new}. "
        "Pedí el adaptador a `ApplicationComposition` en lugar de construirlo acá."
    )


def test_the_exception_list_only_shrinks():
    stale = sorted(KNOWN_EXCEPTIONS - _violators())
    assert not stale, f"ya no violan; quitalos de KNOWN_EXCEPTIONS: {stale}"


def test_the_runtime_sqlite_path_is_declared_once():
    # `runtime_state_path` is the only place that spells the filename; every
    # other module asks the composition root for its stores.
    spelled = sorted(
        path.relative_to(SRC_ROOT).as_posix()
        for path in SRC_ROOT.rglob("*.py")
        if "runtime.sqlite3" in path.read_text(encoding="utf-8")
    )
    assert spelled == ["composition.py"], spelled
