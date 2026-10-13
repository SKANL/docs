"""Shared run context for the document pipeline stage groups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy


@dataclass(frozen=True)
class PipelineContext:
    """Collaborators and mutable run state shared by every stage group.

    ``state`` is the per-run scratchpad the stages communicate through
    (resolved context, renderer, artifact, manifest, verification evidence).
    """

    deps: Any
    output_format: str
    policy: PipelinePolicy | None
    state: dict[str, Any]
    scratch_dirs: list[Path]
    document_root: Path
    document_id: str
    ledger: Any

    @property
    def strict(self) -> bool:
        return self.policy is not None and self.policy.mode in {
            PipelineMode.strict,
            PipelineMode.release,
        }


def stage_success(name: str, detail: str = "") -> tuple[bool, str]:
    return True, detail or f"{name} completed"
