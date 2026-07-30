# src/docs/domain/revision.py
"""Pure diff/summary primitives for the `doc revise` loop (spec:
document-revise "Revise Diff Output"). No I/O -- application/revision.py
orchestrates repositories/services around these."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any


def unified_diff(before: str, after: str, *, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{label} (antes)",
            tofile=f"{label} (después)",
        )
    )


def summarize_change(before: str, after: str) -> str:
    if before == after:
        return "Sin cambios."
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return f"{added} línea(s) añadidas, {removed} línea(s) eliminadas."


@dataclass(frozen=True)
class RevisionResult:
    target_id: str
    before: str
    after: str
    diff: str
    summary: str
    changed_sections: list[str] = field(default_factory=list)
    diff_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "diff": self.diff,
            "summary": self.summary,
            "changed_sections": self.changed_sections,
            "diff_path": self.diff_path,
        }

    def to_markdown(self) -> str:
        lines = [f"# Revisión: `{self.target_id}`", "", self.summary, ""]
        if self.changed_sections:
            lines.append(f"Re-validado: {', '.join(self.changed_sections)} + documento.")
            lines.append("")
        if self.diff:
            lines.append("```diff")
            lines.append(self.diff.rstrip("\n"))
            lines.append("```")
        return "\n".join(lines)
