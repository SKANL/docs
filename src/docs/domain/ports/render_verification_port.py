from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationReport


class RenderVerificationPort(Protocol):
    """Inspect a ready artifact without coupling QA to an output format."""

    def verify(
        self,
        artifact: ArtifactRef,
        profile: RenderProfile,
        preview_dir: Path | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> VerificationReport: ...
