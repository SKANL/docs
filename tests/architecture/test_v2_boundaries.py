"""Architecture guards for the v2 pipeline boundary."""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
V2_ROOTS = (SRC_ROOT / "domain", SRC_ROOT / "application")
V2_MODULES = tuple(
    sorted(
        path
        for root in V2_ROOTS
        for path in root.rglob("*.py")
        if path.name.endswith("_v2.py") or path.name in {"pipeline_kernel.py", "tool_capability.py"}
    )
)

_PLUGIN_IMPORT_PATTERN = re.compile(r"(?:^|\.)plugins?(?:\.|$)")
_PLUGIN_PATH_PATTERN = re.compile(r"(?:^|[/\\])plugins?(?:[/\\]|$)")


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _display(node: ast.AST) -> str:
    return f"line {getattr(node, 'lineno', '?')}"


def test_v2_modules_do_not_import_or_reference_plugin_paths() -> None:
    """The v2 boundary must not couple to installed plugin layouts."""
    violations: list[str] = []
    for path in V2_MODULES:
        tree = _parse(path)
        relative = path.relative_to(SRC_ROOT.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _PLUGIN_IMPORT_PATTERN.search(alias.name):
                        violations.append(f"{relative}:{_display(node)} imports {alias.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module and _PLUGIN_IMPORT_PATTERN.search(node.module):
                violations.append(f"{relative}:{_display(node)} imports {node.module!r}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _PLUGIN_PATH_PATTERN.search(node.value):
                violations.append(f"{relative}:{_display(node)} references plugin path {node.value!r}")

    assert not violations, "v2 modules must not depend on plugin imports or paths:\n" + "\n".join(violations)


def test_domain_modules_do_not_use_subprocess_directly() -> None:
    """External process execution belongs behind application/infrastructure ports."""
    violations: list[str] = []
    domain_root = SRC_ROOT / "domain"
    for path in sorted(domain_root.rglob("*.py")):
        tree = _parse(path)
        relative = path.relative_to(SRC_ROOT.parent)
        subprocess_names = {"subprocess"}
        subprocess_call_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                        subprocess_names.add(alias.asname or alias.name.split(".")[0])
                        violations.append(f"{relative}:{_display(node)} imports subprocess")
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "subprocess" or node.module.startswith("subprocess.")
            ):
                violations.append(f"{relative}:{_display(node)} imports from subprocess")
                subprocess_call_names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id in subprocess_names:
                    violations.append(f"{relative}:{_display(node)} calls subprocess.{node.func.attr}()")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in subprocess_call_names:
                violations.append(f"{relative}:{_display(node)} calls imported subprocess function {node.func.id}()")

    assert not violations, "domain modules must not execute subprocesses directly:\n" + "\n".join(violations)


def test_pipeline_kernel_contains_no_nondeterministic_timestamp_calls() -> None:
    """The planning kernel must remain a deterministic function of its inputs."""
    path = SRC_ROOT / "domain" / "pipeline_kernel.py"
    tree = _parse(path)
    violations: list[str] = []
    nondeterministic_names = {"now", "utcnow", "today", "time", "time_ns"}
    time_module_names = {"time"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    time_module_names.add(alias.asname or "time")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attribute = node.func.attr
        if attribute not in nondeterministic_names:
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Name) and (
            receiver.id in {"datetime", "date"} or receiver.id in time_module_names
        ):
            violations.append(f"{_display(node)} calls {receiver.id}.{attribute}()")
        elif attribute in {"now", "utcnow", "today"}:
            violations.append(f"{_display(node)} calls nondeterministic .{attribute}()")

    assert not violations, "pipeline_kernel must not read wall-clock time:\n" + "\n".join(violations)


def test_application_atomic_transform_v2_does_not_import_system_boundaries_directly() -> None:
    """The v2 application compatibility port must not own process or filesystem mechanics."""
    path = SRC_ROOT / "application" / "atomic_transform_v2.py"
    tree = _parse(path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"os", "subprocess", "tempfile"} or alias.name.startswith(("os.", "subprocess.", "tempfile.")):
                    violations.append(f"{_display(node)} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module and (
            node.module in {"os", "subprocess", "tempfile"} or node.module.startswith(("os.", "subprocess.", "tempfile."))
        ):
            violations.append(f"{_display(node)} imports from {node.module}")

    assert not violations, "application atomic transform must not import process or filesystem boundary modules:\n" + "\n".join(violations)

def test_application_provenance_v2_is_a_thin_reexport_without_persistence_imports() -> None:
    """Filesystem, hashing, and JSON ledger mechanics live in infrastructure."""
    path = SRC_ROOT / "application" / "provenance_v2.py"
    tree = _parse(path)
    forbidden_modules = {"hashlib", "json", "os", "tempfile"}
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_modules:
                    violations.append(f"{_display(node)} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in forbidden_modules:
                violations.append(f"{_display(node)} imports from {node.module}")

    assert not violations, (
        "application provenance must re-export infrastructure behavior rather than own persistence mechanics:\\n"
        + "\\n".join(violations)
    )


def test_workspace_bridge_declares_native_review_and_release_handlers() -> None:
    """The v2 workspace bridge must not regress these stages to implicit gaps."""
    path = SRC_ROOT / "cli" / "commands" / "v2_app.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "_native_document_review",
        "_native_visual_review",
        "_native_package_release",
        "_write_package_archive",
    } <= functions
    assert '"package-release": _callable_stage("package_release") or _native_package_release' in source
    assert '"visual_review": _callable_stage("visual_review") or _native_visual_review' in source
