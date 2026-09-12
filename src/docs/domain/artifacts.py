from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from docs.domain.identity import canonical_json, sha256_content


class ArtifactState(str, Enum):
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


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str
    state: ArtifactState = ArtifactState.READY

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "state": self.state.value}


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class VerificationReport:
    artifact: ArtifactRef
    findings: list[VerificationFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact": self.artifact.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "passed": self.passed,
        }


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
        normalized = tuple(
            artifact
            if isinstance(artifact, ArtifactRef)
            else ArtifactRef(
                str(artifact["path"]),
                str(artifact["sha256"]),
                ArtifactState(artifact.get("state", "ready")),
            )
            for artifact in self.artifacts
        )
        object.__setattr__(self, "artifacts", normalized)

    def to_dict_without_schema(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_hash": self.source_hash,
            "template_hash": self.template_hash,
            "config_hash": self.config_hash,
            "context_hash": self.context_hash,
            "asset_hashes": dict(sorted(self.asset_hashes.items())),
            "renderer_versions": dict(sorted(self.renderer_versions.items())),
            "artifacts": [artifact.to_dict() for artifact in sorted(self.artifacts, key=lambda item: item.path)],
            "verification": self.verification,
            "provenance_run": self.provenance_run,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "docs.build/v2", **self.to_dict_without_schema()}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def attestation(self) -> dict[str, Any]:
        """Return a deterministic, content-addressed statement of this build."""
        payload = self.to_dict()
        return {
            "schema": "docs.attestation/v2",
            "manifest": payload,
            "sha256": sha256_content(payload),
        }

    def validate_for_publication(self) -> None:
        """Reject evidence that cannot attest a publishable build."""
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
            if artifact.state not in {ArtifactState.READY, ArtifactState.PUBLISHED} or not re.fullmatch(r"[0-9a-f]{64}", artifact.sha256):
                raise ValueError("artifacts must have ready/published SHA-256 identities")
        if self.verification.get("passed") is not True:
            raise ValueError("publication requires passed verification")
        if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in self.asset_hashes.values()):
            raise ValueError("asset_hashes must contain SHA-256 digests")
        if not self.renderer_versions:
            raise ValueError("renderer_versions must not be empty")
        if not self.provenance_run:
            raise ValueError("publication requires a provenance run")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BuildManifest:
        if payload.get("schema") != "docs.build/v2":
            raise ValueError("unsupported build manifest schema")
        return cls(
            document_id=str(payload.get("document_id", "")),
            source_hash=str(payload.get("source_hash", "")),
            template_hash=str(payload.get("template_hash", "")),
            config_hash=str(payload.get("config_hash", "")),
            context_hash=str(payload.get("context_hash", "")),
            asset_hashes={str(key): str(value) for key, value in payload.get("asset_hashes", {}).items()},
            renderer_versions={str(key): str(value) for key, value in payload.get("renderer_versions", {}).items()},
            artifacts=tuple(
                ArtifactRef(str(item["path"]), str(item["sha256"]), ArtifactState(item.get("state", "ready")))
                for item in payload.get("artifacts", [])
            ),
            verification=dict(payload.get("verification", {})),
            provenance_run=payload.get("provenance_run"),
        )
