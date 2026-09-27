"""Application use cases for selecting, validating, and retaining render artifacts."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.artifact_build_service import (
    ArtifactBuildError,
    ArtifactBuildService,
    ArtifactValidator,
    ScratchFactory,
)


@dataclass(frozen=True)
class RenderOutcome:
    """Result of a requested render, including validated temporary output."""

    succeeded: bool
    detail: str
    artifact: Path | None = None
    scratch_dir: Path | None = None


class ArtifactRenderService:
    """Build an artifact in isolation and optionally retain an attested render."""

    def __init__(
        self,
        *,
        scratch_factory: ScratchFactory,
        validator: ArtifactValidator,
    ) -> None:
        self._scratch_factory = scratch_factory
        self._validator = validator

    def build_format(
        self,
        *,
        renderers: Mapping[str, Any],
        format_name: str,
        document_id: str,
        config: dict[str, Any],
        scratch_parent: Path,
    ) -> RenderOutcome:
        """Build a specific registered format without changing caller config."""
        renderer = renderers.get(format_name)
        if renderer is None:
            return RenderOutcome(False, f"renderer does not provide {format_name} output")
        format_config = deepcopy(config)
        format_config.setdefault("output", {})["format"] = format_name
        return self._build(
            renderer=renderer,
            format_name=format_name,
            document_id=document_id,
            config=format_config,
            scratch_parent=scratch_parent,
            missing_is_omission=True,
        )

    def render_and_retain(
        self,
        *,
        renderer: Any,
        format_name: str,
        document_id: str,
        config: dict[str, Any],
        runs_dir: Path,
        retained_dir: Path,
        build_token: str,
        directory_guard: Callable[[Path], AbstractContextManager[Any]],
        directory_identity: Callable[[Path], Any],
        assert_directory_identity: Callable[..., None],
    ) -> RenderOutcome:
        """Build and atomically retain the render after checking its directory."""
        if any(path.is_symlink() for path in (runs_dir, retained_dir, *runs_dir.parents)):
            return RenderOutcome(False, "render retention path must not contain symlinked directories")
        retained_dir.mkdir(parents=True, exist_ok=True)
        identity = directory_identity(retained_dir)
        outcome = self._build(
            renderer=renderer,
            format_name=format_name,
            document_id=document_id,
            config=config,
            scratch_parent=runs_dir,
        )
        if not outcome.succeeded or outcome.artifact is None:
            return outcome
        retained = retained_dir / f"{build_token}.{outcome.artifact.name}"
        with directory_guard(retained_dir):
            os.replace(outcome.artifact, retained)
        try:
            assert_directory_identity(retained_dir, identity, operation="render retention")
        except (OSError, RuntimeError) as exc:
            return RenderOutcome(False, str(exc), scratch_dir=outcome.scratch_dir)
        return RenderOutcome(True, str(retained), retained, outcome.scratch_dir)

    def _build(
        self,
        *,
        renderer: Any,
        format_name: str,
        document_id: str,
        config: dict[str, Any],
        scratch_parent: Path,
        missing_is_omission: bool = False,
    ) -> RenderOutcome:
        service = ArtifactBuildService(
            build=lambda doc_id, build_config, output: renderer.build(
                doc_id, build_config, output=output
            ),
            scratch_factory=self._scratch_factory,
            validator=self._validator,
        )
        try:
            result = service.build(
                document_id=document_id,
                config=config,
                output_format=format_name,
                scratch_parent=scratch_parent,
            )
        except ArtifactBuildError as exc:
            if missing_is_omission and exc.reason == "missing":
                return RenderOutcome(True, f"omitted: {exc}")
            return RenderOutcome(False, str(exc))
        return RenderOutcome(True, str(result.artifact), result.artifact, result.scratch_dir)
