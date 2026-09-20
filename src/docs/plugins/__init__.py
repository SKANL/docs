"""Capability-scoped, process-isolated plugin SDK primitives."""

from docs.plugins.manifest import (
    ManifestError,
    PluginManifest,
    generate_sbom,
    manifest_hash,
    manifest_identity,
    plugin_identity,
    validate_manifest,
)
from docs.plugins.registry import PluginPackageInstaller, PluginRegistry, archive_digest, package_digest, verify_sbom
from docs.plugins.runner import PluginRunError, PluginRunner, PluginRunResult

__all__ = [
    "ManifestError",
    "PluginManifest",
    "PluginPackageInstaller",
    "PluginRegistry",
    "PluginRunError",
    "PluginRunResult",
    "PluginRunner",
    "archive_digest",
    "generate_sbom",
    "manifest_hash",
    "manifest_identity",
    "package_digest",
    "plugin_identity",
    "validate_manifest",
    "verify_sbom",
]
