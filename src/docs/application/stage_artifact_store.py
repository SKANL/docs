"""Durable artifact storage for pipeline stage outputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.domain.pipeline_kernel import ArtifactContract, ArtifactRecord
from docs.domain.ports.atomic_file_port import AtomicFilePort


class StageArtifactStore:
    """Write contract-bound artifacts below one explicit storage root."""

    def __init__(self, root: Path, file_writer: AtomicFilePort) -> None:
        self._root = Path(root).absolute()
        self._reject_symlinked_path(self._root, "store root")
        self._file_writer = file_writer

    def write(
        self,
        contract: ArtifactContract,
        relative_path: str,
        content: bytes,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRecord:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or not relative_path:
            raise ValueError(f"artifact path must be relative to the store root: {relative_path!r}")
        target = self._root / relative
        self._reject_symlinked_path(target, "artifact path")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._reject_symlinked_path(target, "artifact path")
        if not target.resolve(strict=False).is_relative_to(self._root.resolve(strict=False)):
            raise ValueError(f"artifact path must remain within the store root: {relative_path!r}")
        with self._file_writer.scratch_dir(target.parent) as scratch:
            candidate = scratch / target.name
            candidate.write_bytes(content)
            self._file_writer.atomic_finalize(candidate, target)
        return ArtifactRecord(
            contract=contract.name,
            path=relative.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            metadata=dict(metadata or {}),
            media_type=contract.media_type,
            size_bytes=len(content),
            state="generated",
        )

    @staticmethod
    def _reject_symlinked_path(path: Path, label: str) -> None:
        if any(candidate.is_symlink() for candidate in (path, *path.parents)):
            raise ValueError(f"{label} must not contain symlinked directories: {path}")

    def write_stage_receipt(
        self,
        contract: ArtifactContract,
        stage: str,
        detail: str,
        *,
        relative_dir: str = "stages",
    ) -> ArtifactRecord:
        """Persist the deterministic receipt for one successful stage."""
        content = (
            json.dumps({"detail": detail, "stage": stage}, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        record = self.write(
            contract,
            f"{relative_dir}/{stage}/{contract.name}.json",
            content,
            metadata={"kind": "stage-receipt"},
        )
        return ArtifactRecord(
            contract=record.contract,
            path=record.path,
            sha256=record.sha256,
            metadata=record.metadata,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            state=record.state,
            producer_stage=stage,
        )
