from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docs.domain.artifacts import RenderProfile, VerificationFinding


class BrowserQaPort(Protocol):
    """Run bounded, isolated browser checks for an HTML artifact.

    Implementations must treat the artifact as hostile input: disable script
    execution where possible, deny unrelated resource requests, and apply a
    finite timeout. The return shape remains findings-only for compatibility.
    """

    def verify(
        self, path: Path, profile: RenderProfile, preview_dir: Path | None
    ) -> list[VerificationFinding]: ...
