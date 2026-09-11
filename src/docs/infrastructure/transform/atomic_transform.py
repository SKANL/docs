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
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError("output_dir must be a directory")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(exist_ok=True)
        versions_dir = output_dir / ".versions"
        versions_dir.mkdir(exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=".scratch-", dir=versions_dir))
        try:
            self._builder(spec, scratch)
            missing = [name for name in spec.expected_outputs if not (scratch / name).is_file()]
            if missing:
                raise ValueError(f"missing declared outputs: {', '.join(missing)}")
            published_dir = self._publish(scratch, output_dir, versions_dir)
            return TransformResult(output_dir=output_dir, outputs=tuple(published_dir / name for name in spec.expected_outputs))
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
    def _publish(scratch: Path, output_dir: Path, versions_dir: Path) -> Path:
        """Install an immutable version, then atomically switch a file pointer.

        Directory replacement is not atomic on Windows. A same-directory file
        replace is, so the current pointer remains valid until the complete new
        version is available and its replacement succeeds.
        """
        version = versions_dir / uuid4().hex
        pending_pointer = output_dir / f".current-{uuid4().hex}.tmp"
        try:
            os.replace(scratch, version)
            pending_pointer.write_text(version.name, encoding="utf-8")
            os.replace(pending_pointer, output_dir / ".current")
        except Exception:
            pending_pointer.unlink(missing_ok=True)
            raise
        return version
