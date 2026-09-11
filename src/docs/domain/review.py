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


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str
    code: str = ""
    dimension: ReviewDimension = ReviewDimension.EDITORIAL

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "message": self.message,
            "code": self.code,
            "dimension": self.dimension.value,
        }


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
