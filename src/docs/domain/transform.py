"""Value types for transactional (all-or-nothing) output publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TransformCallable = Callable[[Path], None]
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class TransformSpec:
    """Inputs and publication contract for one transform."""

    expected_outputs: tuple[str, ...]
    destinations: tuple[Path, ...]
    command: tuple[str, ...] | None = None
    warn_on_failure: bool = False
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS


@dataclass(frozen=True)
class TransformResult:
    ok: bool
    outputs: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
