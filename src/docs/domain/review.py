from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "message": self.message, "code": self.code}


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

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": [issue.to_dict() for issue in self.issues]}
