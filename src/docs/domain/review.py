from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReviewDimension(str, Enum):
    EDITORIAL = "editorial"
    EVIDENCE = "evidence"
    CONSISTENCY = "consistency"
    STRUCTURAL = "structural"
    ACCESSIBILITY = "accessibility"
    VISUAL = "visual"
    REPRODUCIBILITY = "reproducibility"


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str
    code: str = ""
    dimension: ReviewDimension = ReviewDimension.EDITORIAL
    evidence: str | None = None
    resolution_condition: str | None = None
    section: str | None = None
    file: str | None = None
    page: int | None = None
    stage_originator: str | None = None

    def to_dict(self) -> dict[str, str | int]:
        issue: dict[str, str | int] = {
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
            "dimension": self.dimension.value,
        }
        optional_fields = {
            "evidence": self.evidence,
            "resolution_condition": self.resolution_condition,
            "section": self.section,
            "file": self.file,
            "page": self.page,
            "stage_originator": self.stage_originator,
        }
        issue.update({key: value for key, value in optional_fields.items() if value is not None})
        return issue


@dataclass(frozen=True)
class ReviewResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_markdown(self) -> str:
        if not self.issues:
            return "# Revisión\n\nSin hallazgos."
        lines = ["# Revisión", ""]
        for issue in self.issues:
            lines.append(f"- {issue.severity.upper()}: {issue.message}")
        return "\n".join(lines)

    def filter_dimensions(self, dimensions: set[ReviewDimension]) -> ReviewResult:
        """Return findings limited to the requested review dimensions."""
        return ReviewResult([issue for issue in self.issues if issue.dimension in dimensions])

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": [issue.to_dict() for issue in self.issues]}
