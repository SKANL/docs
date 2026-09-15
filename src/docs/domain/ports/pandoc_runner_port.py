from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PandocRunnerPort(Protocol):
    """Runs a prepared pandoc command without exposing process concerns to application code."""

    def run(self, args: Sequence[str], *, check: bool, timeout: int) -> None:
        ...
