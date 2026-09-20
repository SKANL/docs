from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

from docs.plugins.manifest import manifest_hash, plugin_identity, validate_manifest
from docs.plugins.registry import PluginPackageInstaller, PluginRegistry, archive_digest, package_digest, verify_sbom
from docs.plugins.runner import PluginRunError, PluginRunner


def _manifest(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "docs.plugin/v1",
        "id": "example.renderer",
        "version": "1.0.0",
        "entrypoint": ["python", "-c", "print('{}')"],
        "capabilities": ["render"],
    }
    value.update(overrides)
    return value


def _package(path: Path, manifest: dict[str, object], *, extra: bytes = b"metadata") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest, sort_keys=True))
        archive.writestr("package.data", extra)


def test_plugin_package_installer_extracts_atomically_and_verifies_archive_digest(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    _package(archive, _manifest())
    install_root = tmp_path / "installed"

    installed = PluginPackageInstaller(install_root).install(archive)

    assert (installed / "plugin.json").is_file()
    assert (installed / "package.data").read_bytes() == b"metadata"
    assert PluginPackageInstaller(install_root).install(archive) == installed
    assert PluginPackageInstaller(tmp_path / "pinned").install(archive, expected_digest=archive_digest(archive)).is_dir()


def test_plugin_registry_builtin_trust_is_bound_to_the_installed_artifact(tmp_path: Path) -> None:
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    registry = PluginRegistry(trusted_builtin_sources=[manifest_path])

    registry.register(_manifest(), manifest_path, trust="builtin")
    manifest_path.write_text(json.dumps(_manifest(), sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact"):
        registry.register(_manifest(), manifest_path, trust="builtin")


def test_sbom_exposes_declared_and_verified_package_metadata(tmp_path: Path) -> None:
    manifest = _manifest(
        sbom={"format": "docs.sbom/v1", "digest": manifest_hash([{"name": "declared"}])}
    )
    package_root = tmp_path / "package"
    package_root.mkdir()
    (package_root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package_root / "package.data").write_bytes(b"actual")

    report = verify_sbom(manifest, package_root)

    assert report["declared"]["digest"] != report["verified"]["digest"]
    assert report["label"] == "declared-mismatch"
    assert {item["name"] for item in report["verified"]["components"]} == {"package.data", "plugin.json"}


def test_runner_trust_credential_is_bound_to_installed_package_bytes(tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    package_root.mkdir()
    raw = _manifest(entrypoint=[sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"])
    (package_root / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    (package_root / "package.data").write_bytes(b"actual")
    manifest = validate_manifest(raw)
    digest = package_digest(package_root)
    identity = plugin_identity(manifest, digest)

    result = PluginRunner(allow_unsandboxed=True, trusted_credentials={identity: "token"}).run(
        manifest, {}, trusted_token="token", artifact_digest=digest
    )
    assert result.plugin_identity == identity

    with pytest.raises(PluginRunError, match="manifest-bound trusted credential"):
        PluginRunner(allow_unsandboxed=True, trusted_credentials={identity: "token"}).run(
            manifest, {}, trusted_token="token", artifact_digest="0" * 64
        )
