"""Bridge legacy pipeline callables into the v2 runtime contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from docs.application.atomic_transform_v2 import AtomicTransform, TransformSpec
from docs.application.pipeline_executor_v2 import StageHandler
from docs.application.pipeline_registry_v2 import PipelinePlannerV2, PipelineRegistryV2
from docs.application.pipeline_runtime_v2 import PipelineRuntime, PipelineRuntimeReport
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_kernel import ArtifactContract, PipelineDefinition, StageResult, StageSpec
from docs.domain.pipeline_policy import PipelinePolicy
from docs.domain.tool_capability import ToolCapabilityRegistry

LegacyStage = Callable[[], tuple[bool, str] | StageResult]
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
    """The staged output contract for a legacy publish operation."""

    expected_outputs: tuple[str, ...]
    destinations: tuple[Path, ...]
    operation: PublicationOperation


@dataclass(frozen=True)
class LegacyPipelineDependencies:
    """Callable seams that adapt the legacy pipeline's existing dependencies."""

    resolve_config: LegacyStage
    resolve_template: LegacyStage
    resolve_context: LegacyStage
    resolve_assets: LegacyStage
    validate_contracts: LegacyStage
    render: LegacyStage
    audit: LegacyStage
    verify: LegacyStage
    provenance: LegacyStage
    publication: PublicationSpec
    ingest_sources: LegacyStage | None = None
    normalize_sources: LegacyStage | None = None
    compile_structure: LegacyStage | None = None
    evidence_review: LegacyStage | None = None
    consistency_review: LegacyStage | None = None
    package_release: LegacyStage | None = None
    generate_visuals: LegacyStage | None = None
    compose_cover: LegacyStage | None = None
    build_html: LegacyStage | None = None
    build_pdf: LegacyStage | None = None
    structural_audit: LegacyStage | None = None
    accessibility_review: LegacyStage | None = None
    visual_review: LegacyStage | None = None
    reproducibility_check: LegacyStage | None = None


class PipelineServiceV2:
    """Execute legacy operations through a reusable v2 pipeline definition."""

    def __init__(
        self,
        *,
        dependencies: LegacyPipelineDependencies,
        capabilities: ToolCapabilityRegistry,
        ledger: ProvenanceLedgerV2,
        atomic_transform: AtomicTransform,
        policy: PipelinePolicy | None = None,
        run_id_sink: Callable[[str], None] | None = None,
        excluded_stages: frozenset[str] = frozenset(),
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        self._dependencies = dependencies
        self._atomic_transform = atomic_transform
        self.registry = PipelineRegistryV2()
        self.registry.register("document", self._definition(excluded_stages))
        self.planner = PipelinePlannerV2()
        self.definition = self.registry.get("document")
        self._runtime = PipelineRuntime(self.definition, self._handlers(), capabilities, ledger, policy)
        self._run_id_sink = run_id_sink
        self._cleanup = cleanup

    def run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path] = (),
        publish: bool = True,
    ) -> PipelineRuntimeReport:
        """Run the v2 pipeline, optionally stopping before publication."""
        if self._run_id_sink is not None:
            self._run_id_sink(run_id)
        excluded: frozenset[str] = (
            frozenset() if publish else frozenset({"publish-draft", "package-release"})
        )
        if not publish and run_id.startswith("cli-verify-"):
            excluded = excluded | frozenset({"record-provenance"})
        try:
            return self._runtime.run(
                run_id,
                inputs=inputs,
                outputs=self._dependencies.publication.destinations if publish else (),
                excluded_stages=excluded,
            )
        finally:
            if self._cleanup is not None:
                self._cleanup()

    def _handlers(self) -> dict[str, StageHandler]:
        stages = self._dependencies
        handlers: dict[str, StageHandler] = {
            "resolve-config": self._adapt("resolve-config", stages.resolve_config),
            "resolve-template": self._adapt("resolve-template", stages.resolve_template),
            "resolve-context": self._adapt("resolve-context", stages.resolve_context),
            "resolve-assets": self._adapt("resolve-assets", stages.resolve_assets),
            "validate-contracts": self._adapt("validate-contracts", stages.validate_contracts),
            "build-docx": self._adapt("build-docx", stages.render),
            "structural-audit": self._adapt(
                "structural-audit", stages.structural_audit or stages.audit
            ),
            "editorial-review": self._adapt("editorial-review", stages.verify),
            "record-provenance": self._adapt("record-provenance", stages.provenance),
            "publish-draft": self._publish,
        }
        for stage_name, operation in (
            ("ingest-sources", stages.ingest_sources),
            ("normalize-sources", stages.normalize_sources),
            ("compile-structure", stages.compile_structure),
            ("generate-visuals", stages.generate_visuals),
            ("compose-cover", stages.compose_cover),
            ("build-html", stages.build_html),
            ("build-pdf", stages.build_pdf),
            ("structural-audit", stages.structural_audit),
            ("accessibility-review", stages.accessibility_review),
            ("visual-review", stages.visual_review),
            ("reproducibility-check", stages.reproducibility_check),
            ("evidence-review", stages.evidence_review),
            ("consistency-review", stages.consistency_review),
            ("package-release", stages.package_release),
        ):
            if operation is not None:
                handlers[stage_name] = self._adapt(stage_name, operation)
            elif stage_name not in handlers:
                handlers[stage_name] = lambda stage=stage_name: StageResult.unsupported(stage)
        return handlers

    @staticmethod
    def _adapt(name: str, operation: LegacyStage) -> StageHandler:
        def handler() -> StageResult:
            result = operation()
            if isinstance(result, StageResult):
                return result
            ok, detail = result
            return StageResult(name, ok, errors=() if ok else (detail,))

        return handler

    def _publish(self) -> StageResult:
        publication = self._dependencies.publication
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
