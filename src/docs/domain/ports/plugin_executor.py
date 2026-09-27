from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class PluginExecutor(Protocol):
    """Version 1 public boundary for isolated plugin execution."""

    def run(
        self,
        manifest: Any,
        payload: Any,
        publication_dir: Path | None = None,
        *,
        trusted_token: str | None = None,
    ) -> Any: ...
