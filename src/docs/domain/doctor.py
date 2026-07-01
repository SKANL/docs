from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "required": self.required, "detail": self.detail}


@dataclass
class DoctorResult:
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def to_markdown(self) -> str:
        lines = ["# Doctor del arnés", ""]
        for check in self.checks:
            if check.ok:
                marker = "OK"
            elif check.required:
                marker = "FAIL"
            else:
                marker = "WARN"
            lines.append(f"- {marker} `{check.name}`: {check.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": [check.to_dict() for check in self.checks]}
