"""Adapt composition-root stage services into the v2 runtime contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from docs.application.atomic_transform_v2 import AtomicTransform, TransformSpec
from docs.application.pipeline_components_v2 import PipelinePlanner, PipelineRegistry
from docs.application.pipeline_executor_v2 import PipelineReport, StageHandler
from docs.application.pipeline_runtime_v2 import PipelineRuntime, PipelineRuntimeReport
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_kernel import ArtifactContract, ArtifactRecord, PipelineDefinition, StageResult, StageSpec
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
        self._capabilities = capabilities
        self._policy = policy
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
        self._completion_artifacts: dict[Path, bytes | None] | None = None

    def run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path] = (),
        publish: bool = True,
        pipeline_id: str = "document",
        external_artifacts: Iterable[str] | None = None,
    ) -> PipelineRuntimeReport:
        """Run the v2 pipeline, optionally stopping before publication."""
        if pipeline_id not in self._runtimes:
            raise ValueError(f"pipeline is not registered: {pipeline_id}")
        if publish and pipeline_id not in {"document", "document-publish"}:
            raise ValueError(
                "only the full document pipeline or document-publish pipeline may publish"
            )
        succeeded = False
        self._completion_artifacts = {}
        try:
            materialized_external = (
                tuple(external_artifacts) if external_artifacts is not None else None
            )
            definition = self.registry.resolve(pipeline_id).definition
            supplied_external = (
                definition.external_artifacts
                if materialized_external is None and pipeline_id == "document"
                else frozenset(materialized_external or ())
            )
            missing_external = sorted(definition.external_artifacts - supplied_external)
            if missing_external:
                return PipelineRuntimeReport(
                    capabilities=self._capabilities.report(),
                    execution=PipelineReport(
                        (
                            StageResult(
                                "external-prerequisites",
                                False,
                                errors=tuple(
                                    f"required external artifact unavailable: {artifact}"
                                    for artifact in missing_external
                                ),
                            ),
                        )
                    ),
                    provenance=None,
                    succeeded=False,
                )
            if publish:
                missing_capabilities = self._capabilities.missing_required()
                if missing_capabilities:
                    capability_error = tuple(
                        f"required capability unavailable: {name}"
                        for name in missing_capabilities
                    )
                    results = [
                        StageResult("capabilities", False, errors=capability_error)
                    ]
                    for stage_name in ("record-provenance", "package-release", "publish-draft"):
                        if stage_name in {stage.name for stage in definition.stages}:
                            results.append(StageResult(stage_name, False, errors=capability_error))
                    return PipelineRuntimeReport(
                        capabilities=self._capabilities.report(),
                        execution=PipelineReport(tuple(results)),
                        provenance=None,
                        succeeded=False,
                    )
            if self._run_id_sink is not None:
                self._run_id_sink(run_id)
            excluded: frozenset[str] = (
                frozenset() if publish else frozenset({"publish-draft", "package-release"})
            )
            if not publish and run_id.startswith("cli-verify-"):
                excluded = excluded | frozenset({"record-provenance"})
            report = self._runtimes[pipeline_id].run(
                run_id,
                inputs=inputs,
                outputs=self._publication.destinations if publish else (),
                excluded_stages=excluded,
                external_artifacts=supplied_external,
            )
            if publish:
                executed = {result.stage for result in report.execution.results}
                results = list(report.execution.results)
                missing_capabilities = self._capabilities.missing_required()
                publication_block_errors = tuple(
                    f"required capability unavailable: {name}" for name in missing_capabilities
                )
                if publication_block_errors:
                    results = [
                        StageResult(
                            result.stage,
                            False,
                            result.artifacts,
                            result.warnings,
                            publication_block_errors,
                            result.outcome,
                        )
                        if (
                            result.stage in {"record-provenance", "package-release", "publish-draft"}
                            and result.ok
                        )
                        else result
                        for result in results
                    ]
                available = {
                    artifact.contract
                    for result in results
                    if result.ok and result.outcome == "succeeded"
                    for artifact in result.artifacts
                }
                for stage in definition.stages:
                    if (
                        stage.name not in {"package-release", "publish-draft"}
                        or stage.name in executed
                    ):
                        continue
                    unavailable = tuple(
                        artifact for artifact in stage.requires if artifact not in available
                    )
                    publication_error = (
                        "required dependency unavailable: " + ", ".join(unavailable)
                        if unavailable
                        else "; ".join(publication_block_errors or (
                            "required dependency unavailable: " + ", ".join(stage.requires),
                        ))
                    )
                    results.append(
                        StageResult(
                            stage.name,
                            False,
                            errors=(publication_error,),
                        )
                    )
                if len(results) != len(report.execution.results):
                    report = PipelineRuntimeReport(
                        capabilities=report.capabilities,
                        execution=PipelineReport(tuple(results)),
                        provenance=report.provenance,
                        succeeded=False,
                    )
                succeeded = report.succeeded
                return report
            succeeded = report.succeeded
            return report
        finally:
            if not succeeded:
                self._rollback_completion_artifacts()
            self._completion_artifacts = None
            if self._cleanup is not None:
                self._cleanup()

    def _handlers(self) -> dict[str, StageHandler]:
        handlers: dict[str, StageHandler] = {"publish-draft": self._publish}
        for stage_name, operation in self._operations.items():
            handlers[stage_name] = self._adapt(
                stage_name,
                operation,
                f"{stage_name}-complete",
                artifact_root=(
                    self._publication.destinations[0].parent.parent
                    if self._publication.destinations
                    else None
                ),
                artifact_writer=self._write_completion_artifact,
            )
        return handlers

    @staticmethod
    def _adapt(
        name: str,
        operation: StageOperation,
        output_contract: str,
        *,
        artifact_root: Path | None = None,
        artifact_writer: Callable[[str, str, str], ArtifactRecord] | None = None,
    ) -> StageHandler:
        def handler() -> StageResult:
            result = operation()
            if isinstance(result, StageResult):
                return result
            ok, detail = result
            artifacts: tuple[ArtifactRecord, ...] = ()
            if ok and artifact_root is not None and output_contract in {
                "accessibility-review-complete",
                "reproducibility-check-complete",
            }:
                if artifact_writer is not None:
                    artifacts = (artifact_writer(name, output_contract, detail),)
                else:
                    artifact_path = artifact_root / "stages" / f"{output_contract}.json"
                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    content = (detail + "\n").encode("utf-8")
                    artifact_path.write_bytes(content)
                    artifacts = (
                        ArtifactRecord(
                            output_contract,
                            str(artifact_path),
                            hashlib.sha256(content).hexdigest(),
                            producer_stage=name,
                        ),
                    )
            return StageResult(name, ok, artifacts=artifacts, errors=() if ok else (detail,))

        return handler

    def _write_completion_artifact(self, stage: str, contract: str, detail: str) -> ArtifactRecord:
        if not self._publication.destinations:
            raise RuntimeError("completion artifact publication root is unavailable")
        artifact_path = self._publication.destinations[0].parent.parent / "stages" / f"{contract}.json"
        if self._completion_artifacts is not None and artifact_path not in self._completion_artifacts:
            self._completion_artifacts[artifact_path] = (
                artifact_path.read_bytes() if artifact_path.is_file() else None
            )
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        content = (detail + "\n").encode("utf-8")
        artifact_path.write_bytes(content)
        return ArtifactRecord(
            contract,
            str(artifact_path),
            hashlib.sha256(content).hexdigest(),
            producer_stage=stage,
        )

    def _rollback_completion_artifacts(self) -> None:
        if self._completion_artifacts is None:
            return
        for path, previous in self._completion_artifacts.items():
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)

    def _publish(self) -> StageResult:
        publication = self._publication
        result = self._atomic_transform.run(
            TransformSpec(
                expected_outputs=publication.expected_outputs,
                destinations=publication.destinations,
            ),
            operation=publication.operation,
        )
        artifacts: tuple[ArtifactRecord, ...] = ()
        if result.ok and publication.destinations:
            destination = publication.destinations[0]
            if destination.exists():
                content = destination.read_bytes()
                artifacts = (
                    ArtifactRecord(
                        "publish-draft-complete",
                        publication.expected_outputs[0],
                        hashlib.sha256(content).hexdigest(),
                        producer_stage="publish-draft",
                    ),
                )
        return StageResult(
            "publish-draft",
            result.ok,
            artifacts=artifacts,
            warnings=result.warnings,
            errors=() if result.ok else (result.error or "publish failed",),
        )


    @classmethod
    def _definition(cls, excluded_stages: frozenset[str] = frozenset()) -> PipelineDefinition:
        stage_ids = tuple(stage for stage in FULL_STAGE_IDS if stage not in excluded_stages)
        optional_stages = {"generate-visuals", "compose-cover", "package-release"}
        dependencies = {
            "resolve-template": ("resolve-config-complete",),
            "resolve-context": ("resolve-template-complete",),
            "resolve-assets": ("resolve-context-complete",),
            "validate-contracts": ("resolve-assets-complete",),
            "ingest-sources": ("validate-contracts-complete",),
            "normalize-sources": ("ingest-sources-complete",),
            "compile-structure": ("normalize-sources-complete",),
            "generate-visuals": ("compile-structure-complete",),
            "compose-cover": ("compile-structure-complete",),
            "build-docx": ("compile-structure-complete",),
            "build-html": ("build-docx-complete",),
            "build-pdf": ("build-docx-complete",),
            "structural-audit": ("build-docx-complete",),
            "editorial-review": ("structural-audit-complete",),
            "evidence-review": ("structural-audit-complete",),
            "consistency-review": ("structural-audit-complete",),
            "accessibility-review": ("structural-audit-complete",),
            "visual-review": ("structural-audit-complete",),
            "reproducibility-check": ("structural-audit-complete",),
            "record-provenance": tuple(f"{name}-complete" for name in (
                "editorial-review", "evidence-review", "consistency-review",
                "accessibility-review", "visual-review", "reproducibility-check",
            )),
            "package-release": ("record-provenance-complete", "editorial-review-complete"),
            "publish-draft": ("record-provenance-complete", "editorial-review-complete"),
        }
        dependencies = {
            stage_name: tuple(
                artifact
                for artifact in required_artifacts
            )
            for stage_name, required_artifacts in dependencies.items()
            if stage_name in stage_ids
        }
        dependency_artifacts = {
            artifact
            for stage_name in stage_ids
            for artifact in dependencies.get(stage_name, ())
        }
        artifact_names = {
            f"{stage_name}-complete" for stage_name in stage_ids
        } | dependency_artifacts
        produced_names = {f"{stage_name}-complete" for stage_name in stage_ids}
        artifacts = tuple(
            ArtifactContract(
                name,
                required=name
                in {
                    "accessibility-review-complete",
                    "reproducibility-check-complete",
                    "publish-draft-complete",
                },
            )
            for name in sorted(artifact_names)
        )
        stages = tuple(
            StageSpec(
                stage_name,
                requires=dependencies.get(stage_name, ()),
                produces=(f"{stage_name}-complete",),
                after={
                    "evidence-review": ("editorial-review",),
                    "consistency-review": ("evidence-review",),
                    "accessibility-review": ("consistency-review",),
                    "visual-review": ("accessibility-review",),
                    "reproducibility-check": ("visual-review",),
                }.get(stage_name, ()),
                optional=stage_name in optional_stages,
            )
            for stage_name in stage_ids
        )
        return PipelineDefinition(
            artifacts=artifacts,
            stages=stages,
            external_artifacts=frozenset(dependency_artifacts - produced_names),
        )
