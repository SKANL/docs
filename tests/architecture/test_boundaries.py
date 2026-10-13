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
        if path.name.endswith("_current.py") or path.name in {"pipeline_kernel.py", "tool_capability.py"}
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

    for ast_node in ast.walk(tree):
        if not isinstance(ast_node, ast.Call) or not isinstance(ast_node.func, ast.Attribute):
            continue
        attribute = ast_node.func.attr
        if attribute not in nondeterministic_names:
            continue
        receiver = ast_node.func.value
        if isinstance(receiver, ast.Name) and (
            receiver.id in {"datetime", "date"} or receiver.id in time_module_names
        ):
            violations.append(f"{_display(ast_node)} calls {receiver.id}.{attribute}()")
        elif attribute in {"now", "utcnow", "today"}:
            violations.append(f"{_display(ast_node)} calls nondeterministic .{attribute}()")

    assert not violations, "pipeline_kernel must not read wall-clock time:\n" + "\n".join(violations)


def test_source_pipeline_uses_ports_instead_of_dynamic_infrastructure_imports() -> None:
    """Source orchestration must depend on ports, not import adapters at runtime."""
    path = SRC_ROOT / "application" / "source_pipeline.py"
    source = path.read_text(encoding="utf-8")
    tree = _parse(path)
    dynamic_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"import_module", "__import__"}
    ]
    assert not dynamic_imports, "source pipeline must receive infrastructure adapters through ports"
    assert "docs.infrastructure" not in source
    assert "AtomicFilePort" in source
    assert "MarkdownNormalizerPort" in source


def test_pipeline_wiring_receives_infrastructure_collaborators_from_composition() -> None:
    """Pipeline application services may use ports, never import adapters."""
    names = ("pipeline_assembly.py", *_pipeline_sources())
    for name in names:
        source = (SRC_ROOT / "application" / name).read_text(encoding="utf-8")
        assert "docs.infrastructure" not in source, (
            f"application/{name} must receive infrastructure collaborators "
            "from the composition root"
        )


def _pipeline_sources() -> dict[str, str]:
    """Source text of the document pipeline module and its stage-group siblings."""
    app = SRC_ROOT / "application"
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(app.glob("document_pipeline*.py"))
    }


def test_document_pipeline_owns_native_review_and_release_handlers() -> None:
    """The application pipeline, not the CLI adapter, owns these stage fallbacks."""
    sources = _pipeline_sources()
    functions = {
        node.name
        for name, source in sources.items()
        for node in ast.walk(ast.parse(source, filename=name))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"document_review", "native_package_release"} <= functions
    assert "_write_package_archive" not in functions
    assert "deps.package_publications.package" in sources["document_pipeline_publish.py"]
    main = sources["document_pipeline.py"]
    assert 'self.stage_provider.operation("package_release")' in main
    assert "or publish_stages.native_package_release" in main
    assert '"evidence-review": self._review_stage_operation(' in main
    assert '"consistency-review": self._review_stage_operation(' in main
    review_tree = ast.parse(sources["document_pipeline_review.py"])
    review_stage = next(
        node
        for node in ast.walk(review_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "review_stage"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_stage"
        for node in ast.walk(review_stage)
    )

    assert "explicit_stages = assemble_explicit_stage_operations(" in main
    assert '"visual_review": review.visual_review' in main


def test_document_pipeline_keeps_audit_and_verify_fallbacks_callable() -> None:
    source = _pipeline_sources()["document_pipeline.py"]
    assert "return lambda: self.review.review_stage(stage)" in source
    assert '"structural-audit": self._review_stage_operation("structural-audit", build_stages.audit)' in source
    assert '"editorial-review": self._review_stage_operation("editorial-review", build_stages.verify)' in source


def test_v2_composition_does_not_reach_through_current_pipeline_aggregate():
    source = (SRC_ROOT / "cli" / "commands" / "document_app.py").read_text(encoding="utf-8")
    assert "deps.pipeline" not in source
    assert 'v2_native' not in source


def test_cli_api_and_worker_share_the_application_composition_boundary() -> None:
    """Process bootstraps must use the package composition, not local service assembly."""
    cli_source = (SRC_ROOT / "cli" / "main.py").read_text(encoding="utf-8")
    api_source = (SRC_ROOT / "sidecar" / "document_actions.py").read_text(encoding="utf-8")
    worker_source = (SRC_ROOT / "workers" / "composition.py").read_text(encoding="utf-8")

    assert "from docs.composition import compose_application" in cli_source
    assert "from docs.composition import ApplicationComposition, compose_application" in api_source
    assert "from docs.composition import ApplicationComposition" in worker_source
    assert "application: ApplicationComposition" in worker_source
