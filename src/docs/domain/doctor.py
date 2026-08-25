from __future__ import annotations

import re
import unicodedata
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



def match_normalized(declared: str, candidates: list[str]) -> str | None:
    """Find `declared` among `candidates`, tolerating Unicode form.

    A filename can be stored decomposed (NFD: `I` plus a combining acute)
    while a template declares it composed (NFC: `Í`). They are the same name
    to a human and different strings to `Path.exists()`, so a real workspace
    reported a guide PDF as missing while it sat in the directory being
    listed. This harness is Spanish-first; accented filenames are the norm.

    Pure: the caller lists the directory, exactly as `find_manual_like`
    already expects pre-probed input. Exact matches win, and among several
    candidates that normalise alike the first in sorted order is chosen so
    the answer never depends on directory iteration order.
    """
    if declared in candidates:
        return declared
    target = unicodedata.normalize("NFC", declared)
    for candidate in sorted(candidates):
        if unicodedata.normalize("NFC", candidate) == target:
            return candidate
    return None

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
