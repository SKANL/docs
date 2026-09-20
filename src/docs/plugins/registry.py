"""Deterministic discovery and indexing for independent Doc Harness plugins."""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .manifest import ManifestError, PluginManifest, generate_sbom, manifest_identity, validate_manifest


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


class PluginRegistry:
    """Discover manifests without importing or executing plugin code."""

    def __init__(self, *, trusted_builtin_sources: Iterable[Path] = ()) -> None:
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._trusted_builtin_sources = frozenset(Path(source).resolve() for source in trusted_builtin_sources)

    def register(self, raw: dict, source: Path, *, trust: str = "untrusted") -> RegisteredPlugin:
        manifest = validate_manifest(raw)
        current = self._plugins.get(manifest.plugin_id)
        digest = manifest_identity(manifest)
        if trust not in {"untrusted", "builtin"}:
            raise ManifestError("trust must be untrusted or builtin")
        resolved_source = source.resolve()
        if trust == "builtin" and resolved_source not in self._trusted_builtin_sources:
            raise ManifestError("builtin execution requires an allowlisted source")
        candidate = RegisteredPlugin(
            manifest, resolved_source, digest, trust, manifest_identity(manifest),
            dict(manifest.toolchain), generate_sbom(manifest),
            "in_process" if trust == "builtin" else "subprocess",
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
                except (OSError, json.JSONDecodeError, ManifestError):
                    continue
        return self.list()

    def list(self) -> tuple[RegisteredPlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def by_capability(self, capability: str) -> tuple[RegisteredPlugin, ...]:
        return tuple(p for p in self.list() if capability in p.manifest.capabilities)

    def get(self, plugin_id: str) -> RegisteredPlugin | None:
        return self._plugins.get(plugin_id)
