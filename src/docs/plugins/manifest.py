from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "docs.plugin/v1"
ALLOWED_CAPABILITIES = frozenset({"render", "ingest", "transform"})
ALLOWED_PERMISSIONS = frozenset({"read_input", "write_scratch"})
_FIELDS = frozenset({"schema", "api", "id", "version", "entrypoint", "capabilities", "formats", "permissions", "network", "deterministic", "resource_limits", "signature", "sbom", "toolchain"})
_RESOURCE_FIELDS = frozenset({"timeout_seconds", "output_bytes", "scratch_bytes", "scratch_files"})
_SIGNATURE_FIELDS = frozenset({"algorithm", "key_id", "value"})
_SBOM_FIELDS = frozenset({"format", "digest", "components"})
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9]*(?:[._/-][a-z0-9]+)*$")


class ManifestError(ValueError):
    """Raised when a plugin manifest is invalid or requests unsafe access."""


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    entrypoint: tuple[str, ...]
    capabilities: frozenset[str]
    api: str = SCHEMA
    formats: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=lambda: ALLOWED_PERMISSIONS)
    network: bool = False
    deterministic: bool = True
    resource_limits: Mapping[str, int | float] = field(default_factory=dict)
    signature: Mapping[str, str] | None = None
    sbom: Mapping[str, Any] | None = None
    toolchain: Mapping[str, str] = field(default_factory=dict)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest contains non-canonical JSON data") from exc


def manifest_hash(value: Mapping[str, Any] | Any) -> str:
    """Return a stable SHA-256 for JSON-compatible data."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def manifest_document(manifest: PluginManifest) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": SCHEMA, "api": manifest.api, "id": manifest.plugin_id, "version": manifest.version, "entrypoint": list(manifest.entrypoint), "capabilities": sorted(manifest.capabilities), "formats": sorted(manifest.formats), "permissions": sorted(manifest.permissions), "network": manifest.network, "deterministic": manifest.deterministic, "resource_limits": dict(manifest.resource_limits), "toolchain": dict(manifest.toolchain)}
    if manifest.signature is not None:
        result["signature"] = dict(manifest.signature)
    if manifest.sbom is not None:
        result["sbom"] = dict(manifest.sbom)
    return result


def manifest_identity(manifest: PluginManifest) -> str:
    return manifest_hash(manifest_document(manifest))


def _string(value: Any, label: str, *, namespace: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > 4096:
        raise ManifestError(f"{label} must be a safe non-empty string")
    if namespace and not _NAMESPACE.fullmatch(value):
        raise ManifestError(f"{label} must be a safe namespace")
    return value


def _mapping(value: Any, label: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise ManifestError(f"{label} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ManifestError(f"unknown {label} field: {', '.join(sorted(unknown))}")
    return value


def validate_manifest(raw: Mapping[str, Any]) -> PluginManifest:
    if not isinstance(raw, Mapping):
        raise ManifestError("manifest must be an object")
    unknown = set(raw) - _FIELDS
    if unknown:
        raise ManifestError(f"unknown manifest field: {', '.join(sorted(unknown))}")
    if raw.get("schema") != SCHEMA:
        raise ManifestError(f"schema must be {SCHEMA}")
    api = raw.get("api", SCHEMA)
    if api != SCHEMA:
        raise ManifestError(f"api must be {SCHEMA}")
    plugin_id = _string(raw.get("id"), "id", namespace=True)
    if not _PLUGIN_ID.fullmatch(plugin_id):
        raise ManifestError("id must be a safe dotted identifier")
    version = _string(raw.get("version"), "version")
    entrypoint = raw.get("entrypoint")
    if not isinstance(entrypoint, list) or not entrypoint or not all(isinstance(part, str) and part and "\x00" not in part for part in entrypoint):
        raise ManifestError("entrypoint must be a non-empty string list")
    if any(len(part) > 4096 for part in entrypoint):
        raise ManifestError("entrypoint arguments are too long")
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
        raise ManifestError("capabilities must be a string list")
    requested = frozenset(capabilities)
    unsafe = requested - ALLOWED_CAPABILITIES
    if unsafe:
        raise ManifestError(f"unsafe capability requested: {', '.join(sorted(unsafe))}")
    if len(requested) != len(capabilities):
        raise ManifestError("capabilities must not contain duplicates")
    formats_raw = raw.get("formats", [])
    if not isinstance(formats_raw, list) or not all(isinstance(item, str) and _NAMESPACE.fullmatch(item) for item in formats_raw):
        raise ManifestError("formats must be a safe namespace string list")
    if len(set(formats_raw)) != len(formats_raw):
        raise ManifestError("formats must not contain duplicates")
    permissions_raw = raw.get("permissions", sorted(ALLOWED_PERMISSIONS))
    if not isinstance(permissions_raw, list) or not all(isinstance(item, str) for item in permissions_raw):
        raise ManifestError("permissions must be a string list")
    permissions = frozenset(permissions_raw)
    unsafe_permissions = permissions - ALLOWED_PERMISSIONS
    if unsafe_permissions:
        raise ManifestError(f"unsafe permission requested: {', '.join(sorted(unsafe_permissions))}")
    if len(permissions) != len(permissions_raw):
        raise ManifestError("permissions must not contain duplicates")
    network = raw.get("network", False)
    deterministic = raw.get("deterministic", True)
    if not isinstance(network, bool) or not isinstance(deterministic, bool):
        raise ManifestError("network and deterministic must be booleans")
    limits_raw = _mapping(raw.get("resource_limits", {}), "resource_limits", _RESOURCE_FIELDS)
    limits: dict[str, int | float] = {}
    for key, value in limits_raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ManifestError(f"resource limit {key} must be positive")
        limits[key] = value
    signature = raw.get("signature")
    if signature is not None:
        signature = dict(_mapping(signature, "signature", _SIGNATURE_FIELDS))
        for key in ("algorithm", "key_id", "value"):
            _string(signature.get(key), f"signature.{key}")
        if signature["algorithm"].lower() in {"none", "md5"}:
            raise ManifestError("signature algorithm is unsafe")
    sbom = raw.get("sbom")
    if sbom is not None:
        sbom = dict(_mapping(sbom, "sbom", _SBOM_FIELDS))
        if "format" in sbom:
            _string(sbom["format"], "sbom.format", namespace=True)
        if "digest" in sbom and not re.fullmatch(r"[0-9a-f]{64}", _string(sbom["digest"], "sbom.digest")):
            raise ManifestError("sbom.digest must be a SHA-256 hex digest")
        if "components" in sbom and not isinstance(sbom["components"], list):
            raise ManifestError("sbom.components must be a list")
    toolchain_raw = raw.get("toolchain", {})
    if not isinstance(toolchain_raw, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in toolchain_raw.items()):
        raise ManifestError("toolchain must be a string map")
    toolchain = {str(k): _string(v, f"toolchain.{k}") for k, v in toolchain_raw.items()}
    return PluginManifest(plugin_id, version, tuple(entrypoint), requested, api, tuple(formats_raw), permissions, network, deterministic, limits, signature, sbom, toolchain)


def generate_sbom(manifest: PluginManifest, *, toolchain: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build deterministic metadata without importing or running plugin code."""
    declared = dict(manifest.toolchain)
    if toolchain:
        declared.update({str(k): str(v) for k, v in toolchain.items()})
    components: list[dict[str, str]] = [
        {"type": "plugin-manifest", "name": manifest.plugin_id, "version": manifest.version, "digest": manifest_identity(manifest)},
        {"type": "entrypoint", "name": manifest.entrypoint[0], "version": declared.get("runtime", "unknown"), "digest": manifest_hash(list(manifest.entrypoint))},
    ]
    components.extend({"type": "toolchain", "name": key, "version": value, "digest": manifest_hash({key: value})} for key, value in sorted(declared.items()))
    return {"format": "docs.sbom/v1", "components": components, "digest": manifest_hash(components)}
