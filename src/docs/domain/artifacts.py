from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ArtifactState(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"


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
