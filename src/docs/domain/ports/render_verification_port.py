from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationReport


class RenderVerificationPort(Protocol):
    """Inspect a ready artifact without coupling QA to an output format."""

    def verify(
        self, artifact: ArtifactRef, profile: RenderProfile, preview_dir: Path | None = None
    ) -> VerificationReport: ...
