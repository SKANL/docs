"""Provide v2 stages through one composition-root adapter boundary."""

from __future__ import annotations

from typing import Any


class StageProviderV2:
    """Resolve a stage service without leaking composition details to stages."""

    def __init__(self, dependencies: Any) -> None:
        self._dependencies = dependencies

    def get(self, name: str) -> Any:
        """Return the explicitly registered service for ``name`` if callable."""
        direct = getattr(self._dependencies, name, None)
        if direct is not None:
            return direct
        services = getattr(self._dependencies, "pipeline", None)
        return getattr(services, name, None)
