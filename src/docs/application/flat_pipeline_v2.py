"""Declarative compatibility boundary for the remaining flat pipeline sets."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from typing import Any

StageOperation = Callable[[], tuple[bool, str]]

_PREP_STAGES: tuple[tuple[str, bool], ...] = (
    ("doctor", True),
    ("build-rules", False),
    ("review-rules", True),
    ("collect-sources", False),
    ("collect-code-evidence", False),
    ("collect-issues", False),
    ("build-ledger", False),
    ("build-sections", False),
    ("gap-report", True),
    ("pack-context", False),
)


class FlatPipelineV2Adapter:
    """Run flat stages through injected operations, not the legacy executor.

    The operations are still supplied by the existing application services so
    migration does not duplicate stage behavior. This adapter owns ordering,
    fail-fast policy, and the stable legacy summary shape; it is removable
    once callers consume the v2 stage report directly.
    """

    def __init__(
        self,
        *,
        operations: Mapping[str, StageOperation],
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._operations = dict(operations)
        self._clock = clock

    def run(self, stage_set: str, *, strict: bool, stages: tuple[tuple[str, bool], ...] = _PREP_STAGES) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        passed = True
        for name, fail_fast in stages:
            operation = self._operations.get(name)
            started = self._clock()
            if operation is None:
                ok, detail = False, f"stage operation is not configured: {name}"
            else:
                try:
                    ok, detail = operation()
                except Exception as exc:  # stage boundary must remain reportable
                    ok, detail = False, f"ERROR: {type(exc).__name__}: {exc}"
            duration = max(0.0, round(self._clock() - started, 3))
            results.append({"stage": name, "ok": ok, "duration_s": duration, "detail": detail})
            if not ok:
                passed = False
                if fail_fast:
                    break
        return {"stage_set": stage_set, "strict": strict, "passed": passed, "stages": results}

