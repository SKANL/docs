from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from docs.domain.transform import TransformResult, TransformSpec

TransformBuilder = Callable[[TransformSpec, Path], None]


class AtomicTransform:
    """Build a complete output tree off-path, then publish it as one unit."""

    def __init__(self, builder: TransformBuilder) -> None:
        self._builder = builder

    def transform(self, spec: TransformSpec) -> TransformResult:
        self._validate_spec(spec)
        output_dir = Path(spec.output_dir)
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("output_dir must be a directory")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".scratch-", dir=output_dir))
        try:
            self._builder(spec, scratch)
            missing = [name for name in spec.expected_outputs if not (scratch / name).is_file()]
            if missing:
                raise ValueError(f"missing declared outputs: {', '.join(missing)}")
            self._publish(scratch, output_dir, spec.expected_outputs)
            return TransformResult(output_dir=output_dir, outputs=tuple(output_dir / name for name in spec.expected_outputs))
        finally:
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)

    @staticmethod
    def _validate_spec(spec: TransformSpec) -> None:
        if not spec.expected_outputs:
            raise ValueError("expected_outputs must not be empty")
        for name in spec.expected_outputs:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"output must be relative to output_dir: {name}")

    @staticmethod
    def _publish(scratch: Path, output_dir: Path, outputs: tuple[str, ...]) -> None:
        """Atomically replace each complete staged file at its public path.

        A process can stop between files, but no public path is removed or
        partially written: each path resolves to its prior complete file or to
        the new complete staged file.
        """
        for name in outputs:
            target = output_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(scratch / name, target)
