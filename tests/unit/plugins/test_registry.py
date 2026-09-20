from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.plugins.manifest import ManifestError
from docs.plugins.registry import PluginRegistry


def manifest(
    plugin_id: str,
    *,
    capabilities: list[str] | None = None,
    entrypoint: list[str] | None = None,
    **overrides: object,
) -> dict[str, object]:
    value = {
        "schema": "docs.plugin/v1",
        "id": plugin_id,
        "version": "1.0.0",
        "entrypoint": entrypoint or ["python", "-c", "raise SystemExit(1)"],
        "capabilities": capabilities or ["render"],
    }
    value.update(overrides)
    return value


def write_manifest(root: Path, value: dict[str, object], name: str = "plugin.json") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_discovery_is_deterministic_and_sorted_by_plugin_id(tmp_path: Path) -> None:
    first = tmp_path / "z-root"
    second = tmp_path / "a-root"
    write_manifest(first, manifest("zeta"), "nested/plugin.json")
    write_manifest(second, manifest("alpha"), "plugin.json")
    write_manifest(first, manifest("middle"), "plugin.json")

    registry = PluginRegistry()

    assert [plugin.manifest.plugin_id for plugin in registry.discover([first, second])] == [
        "alpha",
        "middle",
        "zeta",
    ]


def test_register_rejects_conflicting_duplicate_manifest() -> None:
    registry = PluginRegistry()
    registry.register(manifest("same"), Path("one/plugin.json"))

    with pytest.raises(ManifestError, match="conflicting plugin registration: same"):
        registry.register(manifest("same", capabilities=["ingest"]), Path("two/plugin.json"))


def test_register_accepts_semantically_duplicate_manifest_with_explicit_defaults() -> None:
    registry = PluginRegistry()
    registry.register(manifest("same"), Path("one/plugin.json"))

    registered = registry.register(
        manifest("same", permissions=["read_input", "write_scratch"], network=False, deterministic=True),
        Path("two/plugin.json"),
    )

    assert registered.manifest.plugin_id == "same"


def test_capability_index_returns_matching_plugins_in_registry_order(tmp_path: Path) -> None:
    write_manifest(tmp_path, manifest("writer", capabilities=["render", "transform"]), "writer/plugin.json")
    write_manifest(tmp_path, manifest("reader", capabilities=["ingest"]), "reader/plugin.json")
    write_manifest(tmp_path, manifest("converter", capabilities=["transform"]), "converter/plugin.json")

    registry = PluginRegistry()
    registry.discover([tmp_path])

    assert [plugin.manifest.plugin_id for plugin in registry.by_capability("transform")] == ["converter", "writer"]
    assert registry.by_capability("missing") == ()


def test_discovery_skips_invalid_manifests(tmp_path: Path) -> None:
    write_manifest(tmp_path, manifest("valid"), "valid/plugin.json")
    write_manifest(tmp_path, {"schema": "docs.plugin/v1", "id": "../invalid"}, "invalid/plugin.json")
    (tmp_path / "broken" ).mkdir()
    (tmp_path / "broken" / "plugin.json").write_text("{not-json", encoding="utf-8")

    assert [plugin.manifest.plugin_id for plugin in PluginRegistry().discover([tmp_path])] == ["valid"]


def test_discovery_never_executes_manifest_entrypoint(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    command = ["python", "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    write_manifest(tmp_path, manifest("inert", entrypoint=command), "plugin.json")

    PluginRegistry().discover([tmp_path])

    assert not marker.exists()


def test_registry_records_identity_sbom_and_subprocess_default(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, manifest("metadata", entrypoint=["python", "-c", "print('{}')"]))
    registered = PluginRegistry().discover([tmp_path])[0]
    assert registered.source == path.resolve()
    assert registered.plugin_identity
    assert registered.sbom["format"] == "docs.sbom/v1"
    assert registered.execution == "subprocess"


def test_builtin_execution_requires_an_allowlisted_source(tmp_path: Path) -> None:
    source = write_manifest(tmp_path, manifest("builtin"))
    with pytest.raises(ManifestError, match="allowlist"):
        PluginRegistry().register(manifest("builtin"), source, trust="builtin")

    registered = PluginRegistry(trusted_builtin_sources=[source]).register(
        manifest("builtin"), source, trust="builtin"
    )
    assert registered.execution == "in_process"


def test_registry_rejects_unknown_trust() -> None:
    with pytest.raises(ManifestError, match="trust"):
        PluginRegistry().register(manifest("bad-trust"), Path("plugin.json"), trust="import")
