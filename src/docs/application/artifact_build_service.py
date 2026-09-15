"""Scratch-only artifact building for the workspace-backed v2 pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from os.path import abspath
from pathlib import Path
from typing import Any, Literal

BuildCallable = Callable[[str, dict[str, Any], Path], Path | None]
ScratchFactory = Callable[[str, Path], Path]
ArtifactValidator = Callable[[Path], tuple[bool, str]]


@dataclass(frozen=True)
class ArtifactBuildResult:
    """A validated artifact that remains in its transient scratch directory."""

    artifact: Path
    scratch_dir: Path
    validation_detail: str


class ArtifactBuildError(RuntimeError):
    """A renderer did not produce a safe artifact suitable for later handling."""

    def __init__(self, reason: Literal["missing", "unsafe", "invalid"], detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class ArtifactBuildService:
    """Build and validate artifacts without retaining, publishing, or copying them."""

    def __init__(
        self,
        *,
        build: BuildCallable,
        scratch_factory: ScratchFactory,
        validator: ArtifactValidator,
    ) -> None:
        self._build = build
        self._scratch_factory = scratch_factory
        self._validator = validator

    def build(
        self,
        *,
        document_id: str,
        config: dict[str, Any],
        output_format: str,
        scratch_parent: Path,
    ) -> ArtifactBuildResult:
        scratch_parent = scratch_parent.resolve()
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch_dir = self._scratch_factory(f".v2-{output_format}-", scratch_parent)
        self._assert_scratch_dir_lexically_contained(scratch_dir, scratch_parent)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        self._assert_scratch_dir(scratch_dir, scratch_parent)
        expected = scratch_dir / f"{document_id}.{output_format}"
        self._assert_artifact_in_scratch(expected, scratch_dir)
        built = self._build(document_id, config, expected)
        if built is None:
            raise ArtifactBuildError("missing", f"{output_format} renderer produced no artifact")
        artifact = Path(built)
        if artifact != expected:
            raise ArtifactBuildError("unsafe", "renderer wrote outside the v2 render scratch directory")
        self._assert_artifact_in_scratch(artifact, scratch_dir)
        if artifact.is_symlink() or not artifact.is_file():
            raise ArtifactBuildError("invalid", "renderer produced no readable artifact")
        try:
            if artifact.stat().st_size == 0:
                raise ArtifactBuildError("invalid", "renderer produced an empty artifact")
            with artifact.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            raise ArtifactBuildError("invalid", f"renderer produced an unreadable artifact: {exc}") from exc
        passed, detail = self._validator(artifact)
        if not passed:
            raise ArtifactBuildError("invalid", detail or "renderer produced an unreadable artifact")
        return ArtifactBuildResult(artifact, scratch_dir, detail)

    @staticmethod
    def _assert_scratch_dir_lexically_contained(scratch_dir: Path, scratch_parent: Path) -> None:
        try:
            Path(abspath(scratch_dir)).relative_to(scratch_parent)
        except ValueError as exc:
            raise ArtifactBuildError(
                "unsafe", "artifact scratch directory is outside the configured scratch parent"
            ) from exc

    @staticmethod
    def _assert_scratch_dir(scratch_dir: Path, scratch_parent: Path) -> None:
        if scratch_dir.is_symlink() or not scratch_dir.is_dir():
            raise ArtifactBuildError("unsafe", "artifact scratch directory is unsafe")
        try:
            scratch_dir.resolve().relative_to(scratch_parent)
        except ValueError as exc:
            raise ArtifactBuildError(
                "unsafe", "artifact scratch directory is outside the configured scratch parent"
            ) from exc

    @staticmethod
    def _assert_artifact_in_scratch(artifact: Path, scratch_dir: Path) -> None:
        try:
            artifact.resolve().relative_to(scratch_dir.resolve())
        except ValueError as exc:
            raise ArtifactBuildError(
                "unsafe", "renderer wrote outside the v2 render scratch directory"
            ) from exc

