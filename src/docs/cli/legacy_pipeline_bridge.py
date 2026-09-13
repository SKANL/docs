"""Finite compatibility boundary for the pre-v2 pipeline CLI.

The v2 composition root must not know the legacy aggregate's constructor or
surface.  Keeping this adapter in the CLI layer makes the migration boundary
explicit and leaves one removable seam once legacy callers are gone.
"""

from __future__ import annotations

from typing import Any

from docs.application.pipeline import PipelineService


class LegacyPipelineBridge:
    """Expose the legacy pipeline only to commands that still require it."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._service = PipelineService(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)
