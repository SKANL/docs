from __future__ import annotations

from typing import Protocol

from docs.domain.transform import TransformResult, TransformSpec


class TransformPort(Protocol):
    def transform(self, spec: TransformSpec) -> TransformResult: ...
