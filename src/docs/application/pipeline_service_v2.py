"""Adapt composition-root stage services into the v2 runtime contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from docs.application.atomic_transform_v2 import AtomicTransform, TransformSpec
from docs.application.pipeline_components_v2 import PipelinePlanner, PipelineRegistry
from docs.application.pipeline_executor_v2 import StageHandler
from docs.application.pipeline_runtime_v2 import PipelineRuntime, PipelineRuntimeReport
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_kernel import ArtifactContract, PipelineDefinition, StageResult, StageSpec
from docs.domain.pipeline_policy import PipelinePolicy
from docs.domain.tool_capability import ToolCapabilityRegistry

StageOperation = Callable[[], tuple[bool, str] | StageResult]
PublicationOperation = Callable[[Path], None]

FULL_STAGE_IDS = (
    "resolve-config",
    "resolve-template",
    "resolve-context",
    "resolve-assets",
    "validate-contracts",
    "ingest-sources",
    "normalize-sources",
    "compile-structure",
    "generate-visuals",
    "compose-cover",
    "build-docx",
    "build-html",
    "build-pdf",
    "structural-audit",
    "editorial-review",
    "evidence-review",
    "consistency-review",
    "accessibility-review",
    "visual-review",
    "reproducibility-check",
    "record-provenance",
    "package-release",
    "publish-draft",
)


@dataclass(frozen=True)
class PublicationSpec:
    """The staged output contract for a publication operation."""

    expected_outputs: tuple[str, ...]
    destinations: tuple[Path, ...]
    operation: PublicationOperation


StageOperationMap = Mapping[str, StageOperation]


class PipelineServiceV2:
    """Execute stage services through a reusable v2 pipeline definition."""

    def __init__(
        self,
        *,
        operations: StageOperationMap,
        publication: PublicationSpec,
        capabilities: ToolCapabilityRegistry,
        ledger: ProvenanceLedgerV2,
        atomic_transform: AtomicTransform,
        policy: PipelinePolicy | None = None,
        run_id_sink: Callable[[str], None] | None = None,
        excluded_stages: frozenset[str] = frozenset(),
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        self._operations = operations
        self._publication = publication
        self._atomic_transform = atomic_transform
        self.registry = PipelineRegistry()
        definition = self._definition(excluded_stages)
        stage_names = {stage.name for stage in definition.stages}
        handlers = {
            name: handler
            for name, handler in self._handlers().items()
            if name in stage_names
        }
        self.registry.register("document", definition, handlers)
        self.registry.register_catalog(definition, handlers)
        registered = self.registry.resolve("document")
        self.planner = PipelinePlanner()
        self.definition = registered.definition
        self.stage_plan = self.planner.plan(self.definition)
        self._runtimes = {
            name: PipelineRuntime(entry.definition, entry.handlers, capabilities, ledger, policy)
            for name, entry in (
                (pipeline, self.registry.resolve(pipeline))
                for pipeline in self.registry.names()
            )
        }
        self._runtime = self._runtimes["document"]
        self._run_id_sink = run_id_sink
        self._cleanup = cleanup

    def run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path] = (),
        publish: bool = True,
        pipeline_id: str = "document",
    ) -> PipelineRuntimeReport:
        """Run the v2 pipeline, optionally stopping before publication."""
        if pipeline_id not in self._runtimes:
            raise ValueError(f"pipeline is not registered: {pipeline_id}")
        if publish and pipeline_id not in {"document", "document-publish"}:
            raise ValueError(
                "only the full document pipeline or document-publish pipeline may publish"
            )
        if self._run_id_sink is not None:
            self._run_id_sink(run_id)
        excluded: frozenset[str] = (
            frozenset() if publish else frozenset({"publish-draft", "package-release"})
        )
        if not publish and run_id.startswith("cli-verify-"):
            excluded = excluded | frozenset({"record-provenance"})
        try:
            return self._runtimes[pipeline_id].run(
                run_id,
                inputs=inputs,
                outputs=self._publication.destinations if publish else (),
                excluded_stages=excluded,
            )
        finally:
            if self._cleanup is not None:
                self._cleanup()

    def _handlers(self) -> dict[str, StageHandler]:
        handlers: dict[str, StageHandler] = {"publish-draft": self._publish}
        for stage_name, operation in self._operations.items():
            handlers[stage_name] = self._adapt(stage_name, operation)
        return handlers

    @staticmethod
    def _adapt(name: str, operation: StageOperation) -> StageHandler:
        def handler() -> StageResult:
            result = operation()
            if isinstance(result, StageResult):
                return result
            ok, detail = result
            return StageResult(name, ok, errors=() if ok else (detail,))

        return handler

    def _publish(self) -> StageResult:
        publication = self._publication
        result = self._atomic_transform.run(
            TransformSpec(
                expected_outputs=publication.expected_outputs,
                destinations=publication.destinations,
            ),
            operation=publication.operation,
        )
        return StageResult(
            "publish-draft",
            result.ok,
            warnings=result.warnings,
            errors=() if result.ok else (result.error or "publish failed",),
        )


    @classmethod
    def _definition(cls, excluded_stages: frozenset[str] = frozenset()) -> PipelineDefinition:
        stage_ids = tuple(stage for stage in FULL_STAGE_IDS if stage not in excluded_stages)
        artifacts = tuple(
            ArtifactContract(f"{stage_name}-complete") for stage_name in stage_ids
        )
        optional_stages = {"generate-visuals", "compose-cover", "package-release"}
        stages = tuple(
            StageSpec(
                stage_name,
                requires=(f"{stage_ids[index - 1]}-complete",)
                if index and stage_ids[index - 1] not in optional_stages
                else (),
                produces=(f"{stage_name}-complete",),
                after=() if index == 0 else (stage_ids[index - 1],),
                optional=stage_name in optional_stages,
            )
            for index, stage_name in enumerate(stage_ids)
        )
        return PipelineDefinition(artifacts=artifacts, stages=stages)
