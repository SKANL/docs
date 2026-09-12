"""Pure execution policies for draft, strict, and release pipelines."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum


class PipelineMode(StrEnum):
    draft = "draft"
    strict = "strict"
    release = "release"


@dataclass(frozen=True)
class PipelinePolicy:
    mode: PipelineMode = PipelineMode.draft
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", PipelineMode(self.mode))
        object.__setattr__(self, "warning_codes", tuple(sorted(set(self.warning_codes))))

    def to_dict(self) -> dict[str, object]:
        return {"mode": self.mode.value, "warning_codes": list(self.warning_codes)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def severity(self, code: str, severity: str) -> str:
        if severity == "warning" and (self.mode in {PipelineMode.strict, PipelineMode.release} or code in self.warning_codes):
            return "error"
        return severity

    def capability_failure(self, *, optional: bool) -> str:
        if optional and self.mode == PipelineMode.draft:
            return "warning"
        return "error"

    def can_publish(self) -> bool:
        return self.mode in {PipelineMode.strict, PipelineMode.release}
