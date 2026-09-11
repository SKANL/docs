from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from docs.domain.transform import TransformResult, TransformSpec

TransformBuilder = Callable[[TransformSpec, Path], None]


class AtomicTransform:
    """Build a complete output tree off-path, then publish it as one unit."""

    def __init__(self, builder: TransformBuilder) -> None:
        self._builder = builder

    def transform(self, spec: TransformSpec) -> TransformResult:
        self._validate_spec(spec)
        output_dir = Path(spec.output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.scratch-", dir=output_dir.parent))
        try:
            self._builder(spec, scratch)
            missing = [name for name in spec.expected_outputs if not (scratch / name).is_file()]
            if missing:
                raise ValueError(f"missing declared outputs: {', '.join(missing)}")
            self._publish(scratch, output_dir)
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
    def _publish(scratch: Path, output_dir: Path) -> None:
        backup = output_dir.with_name(f".{output_dir.name}.previous-{uuid4().hex}")
        moved_previous = False
        try:
            if output_dir.exists():
                os.replace(output_dir, backup)
                moved_previous = True
            os.replace(scratch, output_dir)
        except Exception:
            if moved_previous and backup.exists() and not output_dir.exists():
                os.replace(backup, output_dir)
            raise
        else:
            if moved_previous:
                shutil.rmtree(backup, ignore_errors=True)
