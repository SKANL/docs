from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from docs.domain.identity import canonical_json, sha256_content


class ArtifactState(str, Enum):
    PLANNED = "planned"
    GENERATED = "generated"
    VERIFIED = "verified"
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True)
class RenderProfile:
    """Declarative expectations shared by every renderable artifact type.

    Previews are optional by default; ``require_previews`` makes their
    unavailability a reported requirement instead of silently requesting one.
    """

    format: str
    expected_page_size: tuple[float, float] | None = None
    require_previews: bool = False
    allow_blank_pages: bool = False
    preview_dpi: int = 150
    baseline_dir: Path | None = None
    minimum_similarity: float = 0.75
    baseline_strict: bool = False


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str
    state: ArtifactState = ArtifactState.READY
    media_type: str | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("artifact path must not be empty")
        if not isinstance(self.sha256, str):
            raise ValueError("artifact sha256 must be a string")
        if self.media_type is not None and (not isinstance(self.media_type, str) or not self.media_type):
            raise ValueError("artifact media_type must be a non-empty string")
        if self.size_bytes is not None and type(self.size_bytes) is not int:
            raise ValueError("artifact size_bytes must be an integer")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("artifact size_bytes must not be negative")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "path": self.path,
            "sha256": self.sha256,
            "state": self.state.value,
        }
        if self.media_type is not None:
            payload["media_type"] = self.media_type
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        return payload


def _parse_artifact_entry(entry: Any) -> ArtifactRef:
    if not isinstance(entry, Mapping):
        raise ValueError("invalid artifact entry: expected a mapping")

    values: dict[str, str] = {}
    for field_name in ("path", "sha256"):
        if field_name not in entry:
            raise ValueError(f"invalid artifact entry: artifact {field_name} is required")
        value = entry[field_name]
        if not isinstance(value, str):
            raise ValueError(f"invalid artifact entry: artifact {field_name} must be a string")
        values[field_name] = value

    state = entry.get("state", "ready")
    if not isinstance(state, str):
        raise ValueError("invalid artifact entry: artifact state must be a string")
    try:
        artifact_state = ArtifactState(state)
    except ValueError as exc:
        allowed_states = ", ".join(item.value for item in ArtifactState)
        raise ValueError(
            f"invalid artifact entry: artifact state must be one of: {allowed_states}; got {state!r}"
        ) from exc

    try:
        if "media_type" in entry and entry.get("media_type") is None:
            raise ValueError("artifact media_type must be a non-empty string")
        if "size_bytes" in entry and entry.get("size_bytes") is None:
            raise ValueError("artifact size_bytes must be an integer")
        size_bytes = entry.get("size_bytes")
        return ArtifactRef(
            values["path"],
            values["sha256"],
            artifact_state,
            media_type=entry.get("media_type"),
            size_bytes=size_bytes,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(
            "invalid artifact entry: expected valid media_type and size_bytes values"
        ) from exc


def _validate_renderer_versions(renderer_versions: object) -> None:
    if not isinstance(renderer_versions, Mapping):
        raise ValueError("renderer_versions must be a mapping")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in renderer_versions.items()
    ):
        raise ValueError("renderer_versions must contain string keys and values")


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    message: str
    severity: str = "error"
    path: str | None = None
    page: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    dimension: str | None = None
    resolution: str | None = None
    section: str | None = None
    stage: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        for key in ("path", "page", "dimension", "resolution", "section", "stage"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.evidence:
            payload["evidence"] = dict(sorted(self.evidence.items()))
        return payload


@dataclass(frozen=True)
class VerificationReport:
    artifact: ArtifactRef
    findings: list[VerificationFinding] = field(default_factory=list)
    checked_artifacts: list[ArtifactRef] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "artifact": self.artifact.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "passed": self.passed,
        }
        if self.checked_artifacts:
            payload["checked_artifacts"] = [
                artifact.to_dict() for artifact in self.checked_artifacts
            ]
        return payload


@dataclass(frozen=True)
class BuildManifest:
    """Deterministic manifest for one compiled document build."""

    document_id: str
    source_hash: str = ""
    template_hash: str = ""
    config_hash: str = ""
    context_hash: str = ""
    asset_hashes: dict[str, str] = field(default_factory=dict)
    renderer_versions: dict[str, str] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    verification: dict[str, Any] = field(default_factory=dict)
    provenance_run: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "document_id",
            "source_hash",
            "template_hash",
            "config_hash",
            "context_hash",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise ValueError(f"{field_name} must be a string")
        normalized = tuple(
            artifact
            if isinstance(artifact, ArtifactRef)
            else _parse_artifact_entry(artifact)
            for artifact in self.artifacts
        )
        object.__setattr__(self, "artifacts", normalized)
        _validate_renderer_versions(self.renderer_versions)

    def _identity_dict_without_schema(self) -> dict[str, Any]:
        _validate_renderer_versions(self.renderer_versions)
        identity_artifacts = [
            {
                **artifact.to_dict(),
                # Workspace-specific absolute paths are publication metadata,
                # not build identity. Keep only their stable artifact name;
                # preserve relative paths so distinct artifact locations do
                # not collapse to the same identity.
                "path": (
                    Path(artifact.path).name
                    if Path(artifact.path).is_absolute()
                    else Path(artifact.path).as_posix()
                ),
            }
            for artifact in self.artifacts
        ]
        return {
            "document_id": self.document_id,
            "source_hash": self.source_hash,
            "template_hash": self.template_hash,
            "config_hash": self.config_hash,
            "context_hash": self.context_hash,
            "asset_hashes": dict(sorted(self.asset_hashes.items())),
            "renderer_versions": dict(sorted(self.renderer_versions.items())),
            "artifacts": sorted(
                identity_artifacts,
                key=lambda item: (
                    str(item["path"]),
                    str(item.get("media_type", "")),
                    str(item["sha256"]),
                ),
            ),
            "verification": self.verification,
        }

    def to_dict_without_schema(self) -> dict[str, Any]:
        _validate_renderer_versions(self.renderer_versions)
        return {
            "document_id": self.document_id,
            "source_hash": self.source_hash,
            "template_hash": self.template_hash,
            "config_hash": self.config_hash,
            "context_hash": self.context_hash,
            "asset_hashes": dict(sorted(self.asset_hashes.items())),
            "renderer_versions": dict(sorted(self.renderer_versions.items())),
            "artifacts": [artifact.to_dict() for artifact in sorted(
                self.artifacts,
                key=lambda item: (item.path, item.media_type or "", item.sha256),
            )],
            "verification": self.verification,
            "provenance_run": self.provenance_run,
        }

    def to_identity_dict(self) -> dict[str, Any]:
        """Return the content-addressed representation, excluding run metadata."""
        return {"schema": "docs.build/v2", **self._identity_dict_without_schema()}

    def identity(self) -> str:
        """Return the stable SHA-256 identity of the build inputs and outputs."""
        return sha256_content(self.to_identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "docs.build/v2", **self.to_dict_without_schema()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def attestation(self) -> dict[str, Any]:
        """Return a deterministic, content-addressed statement of this build."""
        payload = self.to_identity_dict()
        return {
            "schema": "docs.attestation/v2",
            "manifest": payload,
            "sha256": self.identity(),
        }

    def validate_for_publication(self) -> None:
        """Reject evidence that cannot attest a publishable build."""
        _validate_renderer_versions(self.renderer_versions)
        if not self.document_id:
            raise ValueError("document_id must not be empty")
        for name, digest in (
            ("source_hash", self.source_hash),
            ("template_hash", self.template_hash),
            ("config_hash", self.config_hash),
            ("context_hash", self.context_hash),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"{name} must be a SHA-256 digest")
        if not self.artifacts:
            raise ValueError("at least one artifact is required")
        for artifact in self.artifacts:
            if not isinstance(artifact.path, str):
                raise ValueError("artifact path must be a string")
            if artifact.state not in {ArtifactState.READY, ArtifactState.VERIFIED, ArtifactState.PUBLISHED} or not re.fullmatch(r"[0-9a-f]{64}", artifact.sha256):
                raise ValueError("artifacts must have verified/ready/published SHA-256 identities")
        if self.verification.get("passed") is not True:
            raise ValueError("publication requires passed verification")
        if any(not isinstance(digest, str) for digest in self.asset_hashes.values()):
            raise ValueError("asset_hashes must contain string values")
        if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in self.asset_hashes.values()):
            raise ValueError("asset_hashes must contain SHA-256 digests")
        if not self.renderer_versions:
            raise ValueError("renderer_versions must not be empty")
        if not isinstance(self.provenance_run, str) or not self.provenance_run:
            raise ValueError("publication requires a provenance run")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BuildManifest:
        if not isinstance(payload, Mapping):
            raise ValueError("build manifest must be a mapping")
        if payload.get("schema") != "docs.build/v2":
            raise ValueError("unsupported build manifest schema")
        asset_hashes = payload.get("asset_hashes", {})
        renderer_versions = payload.get("renderer_versions", {})
        if not isinstance(asset_hashes, Mapping):
            raise ValueError("asset_hashes must be a mapping")
        if any(not isinstance(value, str) for value in asset_hashes.values()):
            raise ValueError("asset_hashes must contain string values")
        _validate_renderer_versions(renderer_versions)
        artifacts = payload.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be a list")
        verification = payload.get("verification", {})
        if not isinstance(verification, Mapping):
            raise ValueError("verification must be a mapping")
        return cls(
            document_id=payload.get("document_id", ""),
            source_hash=payload.get("source_hash", ""),
            template_hash=payload.get("template_hash", ""),
            config_hash=payload.get("config_hash", ""),
            context_hash=payload.get("context_hash", ""),
            asset_hashes={str(key): value for key, value in asset_hashes.items()},
            renderer_versions=dict(renderer_versions),
            artifacts=tuple(_parse_artifact_entry(item) for item in artifacts),
            verification=dict(verification),
            provenance_run=payload.get("provenance_run"),
        )
