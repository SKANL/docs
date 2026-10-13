from __future__ import annotations

from typing import Protocol

from docs.domain.transform import TransformCallable, TransformResult, TransformSpec


class TransformPort(Protocol):
    """Run one transform and publish its outputs atomically."""

    def run(self, spec: TransformSpec, operation: TransformCallable | None = None) -> TransformResult: ...
