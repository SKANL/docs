from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from docs.domain.source_role import NORMATIVE_LEXICON

# Extensions a manual/guide is plausibly shipped as -- restricts the
# keyword match so an unrelated binary asset (e.g. `manual.png`) never
# false-positives (design.md item E: "auto-detect ... by content").
_MANUAL_LIKE_EXTENSIONS = frozenset({"pdf", "docx", "odt", "md", "txt"})
_WORD_RE = re.compile(r"[a-z0-9]+")


def find_manual_like(candidates: list[tuple[str, str]]) -> str | None:
    """Pure predicate (design.md item E): given `(relative_path, extension)`
    pairs already probed by a `ContentProbePort` adapter (I/O stays in the
    adapter), returns the first -- sorted, deterministic -- relative path
    whose extension is manual-like AND whose path/filename contains a
    normative-guide keyword. Reuses `source_role.NORMATIVE_LEXICON`, the
    same vocabulary folder-lexicon classification already uses -- never a
    second copy. Returns `None` when nothing matches; the caller decides how
    to report that (fail-open, never a silent guess)."""
    matches = sorted(
        relative_path
        for relative_path, extension in candidates
        if extension.lower().lstrip(".") in _MANUAL_LIKE_EXTENSIONS
        and set(_WORD_RE.findall(relative_path.casefold())) & NORMATIVE_LEXICON
    )
    return matches[0] if matches else None


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
