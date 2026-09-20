"""Deterministic discovery and indexing for independent Doc Harness plugins."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import (
    ManifestError,
    PluginManifest,
    manifest_hash,
    manifest_identity,
    plugin_identity,
    validate_manifest,
)


@dataclass(frozen=True)
class RegisteredPlugin:
    manifest: PluginManifest
    source: Path
    digest: str
    trust: str = "untrusted"
    plugin_identity: str = ""
    toolchain: dict[str, str] | None = None
    sbom: dict[str, object] | None = None
    execution: str = "subprocess"
    artifact_digest: str = ""


def package_digest(path: Path) -> str:
    """Hash the complete installed package, not only its manifest."""
    root = Path(path)
    if root.is_file():
        root = root.parent
    if not root.exists():
        return manifest_hash({"missing_artifact": root.as_posix()})
    digest = hashlib.sha256()
    if any(item.is_symlink() for item in root.rglob("*")):
        raise ValueError("plugin artifact must not contain symlinks")
    files = sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix())
    for item in files:
        relative = item.relative_to(root).as_posix().encode("utf-8")
        content = item.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def archive_digest(path: Path) -> str:
    """Hash the distributable archive bytes for supply-chain pinning."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_sbom(raw_manifest: Mapping[str, Any], package_root: Path) -> dict[str, Any]:
    """Return side-by-side declared and observed package metadata."""
    declared = dict(raw_manifest.get("sbom") or {})
    components = []
    root = Path(package_root)
    for item in sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(root).as_posix()):
        content = item.read_bytes()
        components.append(
            {
                "type": "package-file",
                "name": item.relative_to(root).as_posix(),
                "size": len(content),
                "digest": hashlib.sha256(content).hexdigest(),
            }
        )
    verified = {"format": "docs.sbom/v1", "components": components, "digest": manifest_hash(components)}
    label = "verified" if declared and declared.get("digest") == verified["digest"] else (
        "declared-mismatch" if declared else "verified-only"
    )
    return {"format": verified["format"], "declared": declared, "verified": verified, "label": label}


class PluginPackageInstaller:
    """Install a plugin archive without executing code and with atomic publication."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def install(self, package: Path, *, expected_digest: str | None = None) -> Path:
        package = Path(package).resolve()
        with tempfile.TemporaryDirectory(prefix=".plugin-install-", dir=self.root) as temporary:
            staged = Path(temporary) / "package"
            if package.is_dir():
                if any(item.is_symlink() for item in package.rglob("*")):
                    raise ManifestError("plugin package directories must not contain symlinks")
                shutil.copytree(package, staged, symlinks=False)
            else:
                self._extract_archive(package, staged)
            manifest_path = staged / "plugin.json"
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = validate_manifest(raw)
            except (OSError, json.JSONDecodeError, TypeError, ManifestError) as exc:
                raise ManifestError("plugin package must contain a valid plugin.json") from exc
            artifact = package_digest(staged)
            archive = archive_digest(package) if package.is_file() else None
            if expected_digest is not None and expected_digest not in {artifact, archive}:
                raise ManifestError("plugin package artifact digest does not match expected digest")
            destination = self.root / manifest.plugin_id / manifest.version
            if destination.exists():
                if package_digest(destination) == artifact:
                    return destination
                raise ManifestError("plugin package destination already contains a different artifact")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
            return destination

    @staticmethod
    def _extract_archive(package: Path, destination: Path) -> None:
        if not package.is_file():
            raise ManifestError("plugin package must be a directory or archive")
        destination.mkdir(parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(package) as archive:
                seen: set[str] = set()
                for member in archive.infolist():
                    name = member.filename.replace("\\", "/")
                    target = Path(name)
                    if not name or target.is_absolute() or ".." in target.parts or name in seen:
                        raise ManifestError("plugin package contains an unsafe or duplicate path")
                    seen.add(name)
                    if member.is_dir():
                        continue
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ManifestError("plugin package must not contain symlinks")
                    output = destination / target
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(member))
        except zipfile.BadZipFile as exc:
            raise ManifestError("plugin package is not a valid zip archive") from exc


class PluginRegistry:
    """Discover manifests without importing or executing plugin code."""

    def __init__(self, *, trusted_builtin_sources: Iterable[Path] = ()) -> None:
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._trusted_builtin_sources = {
            Path(source).resolve(): package_digest(Path(source)) for source in trusted_builtin_sources
        }

    def register(self, raw: dict, source: Path, *, trust: str = "untrusted") -> RegisteredPlugin:
        manifest = validate_manifest(raw)
        current = self._plugins.get(manifest.plugin_id)
        digest = manifest_identity(manifest)
        if trust not in {"untrusted", "builtin"}:
            raise ManifestError("trust must be untrusted or builtin")
        resolved_source = source.resolve()
        artifact = package_digest(resolved_source)
        if trust == "builtin":
            expected_artifact = self._trusted_builtin_sources.get(resolved_source)
            if expected_artifact is None:
                raise ManifestError("builtin execution requires an allowlisted source")
            if expected_artifact != artifact:
                raise ManifestError("builtin trust requires a matching artifact digest")
        sbom = verify_sbom(raw, resolved_source.parent)
        candidate = RegisteredPlugin(
            manifest, resolved_source, digest, trust, plugin_identity(manifest, artifact),
            dict(manifest.toolchain),
            {"format": sbom["format"], "components": sbom["verified"]["components"], "digest": sbom["verified"]["digest"], **sbom},
            "in_process" if trust == "builtin" else "subprocess",
            artifact,
        )
        if current is not None and current.digest != digest:
            raise ManifestError(f"conflicting plugin registration: {manifest.plugin_id}")
        if current is not None and current.manifest.version != manifest.version:
            raise ManifestError(f"conflicting plugin version: {manifest.plugin_id}")
        self._plugins[manifest.plugin_id] = candidate
        return candidate

    def discover(self, roots: Iterable[Path]) -> tuple[RegisteredPlugin, ...]:
        for root in sorted((Path(r) for r in roots), key=lambda p: p.as_posix()):
            if not root.exists():
                continue
            for path in sorted(root.rglob("plugin.json"), key=lambda p: p.as_posix()):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    self.register(raw, path, trust="untrusted")
                except (OSError, ValueError, json.JSONDecodeError, ManifestError):
                    continue
        return self.list()

    def list(self) -> tuple[RegisteredPlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def by_capability(self, capability: str) -> tuple[RegisteredPlugin, ...]:
        return tuple(p for p in self.list() if capability in p.manifest.capabilities)

    def get(self, plugin_id: str) -> RegisteredPlugin | None:
        return self._plugins.get(plugin_id)
