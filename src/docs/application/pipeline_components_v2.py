"""Reusable application components for composing v2 pipelines."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.atomic_transform_v2 import (
    AtomicTransform,
    TransformResult,
    TransformSpec,
)
from docs.application.pipeline_executor_v2 import PipelineReport, StageHandler
from docs.domain.pipeline_kernel import ArtifactContract, ArtifactRecord, PipelineDefinition, StageResult, StageSpec


@dataclass(frozen=True)
class PublicPipelineSpec:
    """A user-facing pipeline name and its reusable stage boundary."""

    pipeline_id: str
    stages: tuple[str, ...]


PUBLIC_PIPELINES: tuple[PublicPipelineSpec, ...] = (
    PublicPipelineSpec("source-ingest", ("resolve-config", "resolve-context", "resolve-assets", "ingest-sources")),
    PublicPipelineSpec("document-prepare", ("normalize-sources", "compile-structure")),
    PublicPipelineSpec("document-build", ("generate-visuals", "compose-cover", "build-docx", "build-html", "build-pdf")),
    PublicPipelineSpec("document-verify", ("structural-audit", "editorial-review", "evidence-review", "consistency-review", "accessibility-review", "visual-review", "reproducibility-check")),
    PublicPipelineSpec("document-publish", ("record-provenance", "publish-draft")),
    PublicPipelineSpec("document-package", ("package-release",)),
    PublicPipelineSpec("document-diff", ()),
    PublicPipelineSpec("document-inspect", ()),
)


@dataclass(frozen=True)
class RegisteredPipeline:
    """A validated definition and its stage implementations."""

    definition: PipelineDefinition
    handlers: Mapping[str, StageHandler]


class PipelineRegistry:
    """Register named v2 pipelines without changing executor semantics."""

    def __init__(self) -> None:
        self._pipelines: dict[str, RegisteredPipeline] = {}

    def register(
        self,
        name: str,
        definition: PipelineDefinition,
        handlers: Mapping[str, StageHandler],
    ) -> None:
        if not name:
            raise ValueError("pipeline name must not be empty")
        if name in self._pipelines:
            raise ValueError(f"pipeline already registered: {name}")
        definition.validate()
        unknown_handlers = set(handlers) - {stage.name for stage in definition.stages}
        if unknown_handlers:
            raise ValueError(f"handlers reference unknown stages: {', '.join(sorted(unknown_handlers))}")
        self._pipelines[name] = RegisteredPipeline(definition, dict(handlers))

    def names(self) -> tuple[str, ...]:
        """Return registered pipeline names in deterministic order."""
        return tuple(sorted(self._pipelines))

    def register_catalog(
        self, definition: PipelineDefinition, handlers: Mapping[str, StageHandler]
    ) -> None:
        """Register each public boundary as a real, independently valid DAG.

        Requirements crossing a boundary become external artifacts. This keeps
        a sub-pipeline honest: it can be planned and executed independently,
        while the full document pipeline remains the composition used by the
        workspace build command.
        """
        stage_by_name = {stage.name: stage for stage in definition.stages}
        artifact_by_name = {artifact.name: artifact for artifact in definition.artifacts}
        for public in PUBLIC_PIPELINES:
            selected = tuple(name for name in public.stages if name in stage_by_name)
            selected_set = set(selected)
            stages: list[StageSpec] = []
            required_external: set[str] = set()
            produced = {artifact for name in selected for artifact in stage_by_name[name].produces}
            for name in selected:
                original = stage_by_name[name]
                requires = tuple(original.requires)
                required_external.update(artifact for artifact in requires if artifact not in produced)
                stages.append(
                    StageSpec(
                        original.name,
                        requires=requires,
                        produces=original.produces,
                        after=tuple(predecessor for predecessor in original.after if predecessor in selected_set),
                        optional=original.optional,
                    )
                )
            artifact_names = {artifact for stage in stages for artifact in (*stage.requires, *stage.produces)}
            sub_definition = PipelineDefinition(
                artifacts=tuple(artifact_by_name[name] for name in sorted(artifact_names) if name in artifact_by_name),
                stages=tuple(stages),
                external_artifacts=frozenset(required_external),
            )
            self.register(public.pipeline_id, sub_definition, {name: handlers[name] for name in selected if name in handlers})

    def resolve(self, name: str) -> RegisteredPipeline:
        try:
            return self._pipelines[name]
        except KeyError as exc:
            raise KeyError(f"pipeline is not registered: {name}") from exc


class PipelinePlanner:
    """Expose a definition's deterministic stage order as stage contracts."""

    def plan(self, definition: PipelineDefinition) -> tuple[StageSpec, ...]:
        stages = {stage.name: stage for stage in definition.stages}
        return tuple(stages[name] for name in definition.plan())


class ArtifactStore:
    """Write contract-bound artifacts below one explicit storage root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return ArtifactRecord(
            contract=contract.name,
            path=relative.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            metadata=dict(metadata or {}),
        )


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


class RunReporter:
    """Create the existing stable execution report from stage results."""

    def report(self, results: Iterable[StageResult]) -> PipelineReport:
        return PipelineReport(tuple(results))
