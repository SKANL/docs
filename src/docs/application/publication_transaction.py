"""Atomic publication transaction for staged document outputs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from docs.application.atomic_transform import AtomicTransform, TransformResult, TransformSpec


@dataclass(frozen=True)
class Publication:
    """One staged relative output and its public destination."""

    relative_path: str
    destination: Path
    content: bytes


class PublicationTransaction:
    """Publish artifact bytes through the v2 atomic-transform boundary."""

    def __init__(self, transform: AtomicTransform | None = None) -> None:
        self._transform = transform or AtomicTransform()

    def publish(self, publications: Sequence[Publication]) -> TransformResult:
        if not publications:
            raise ValueError("at least one publication is required")
        spec = TransformSpec(
            expected_outputs=tuple(publication.relative_path for publication in publications),
            destinations=tuple(publication.destination for publication in publications),
        )

        def write_outputs(scratch: Path) -> None:
            for publication in publications:
                staged = scratch / publication.relative_path
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(publication.content)

        return self._transform.run(spec, write_outputs)
