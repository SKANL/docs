"""Capability-scoped, process-isolated plugin SDK primitives."""

from docs.plugins.manifest import (
    ManifestError,
    PluginManifest,
    generate_sbom,
    manifest_hash,
    manifest_identity,
    validate_manifest,
)
from docs.plugins.runner import PluginRunError, PluginRunner, PluginRunResult

__all__ = [
    "ManifestError",
    "PluginManifest",
    "PluginRunError",
    "PluginRunResult",
    "PluginRunner",
    "generate_sbom",
    "manifest_hash",
    "manifest_identity",
    "validate_manifest",
]
