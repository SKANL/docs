"""Provide v2 stages through one composition-root adapter boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class StageProviderV2:
    """Resolve a stage service without leaking composition details to stages."""

    def __init__(self, services: Mapping[str, Any]) -> None:
        self._services = dict(services)

    def get(self, name: str) -> Any:
        """Return the explicitly registered service for ``name`` if callable."""
        return self._services.get(name)
