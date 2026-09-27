"""Adapt composition-root stage services into the v2 runtime contracts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from docs.application.atomic_transform import AtomicTransform, TransformSpec
from docs.application.pipeline_executor import PipelineReport, StageHandler, _PipelineExecutor
from docs.application.pipeline_registry import PipelinePlanner, PipelineRegistry
from docs.application.provenance import ProvenanceLedger
from docs.application.stage_artifact_store import StageArtifactStore
from docs.domain.pipeline_kernel import (
    ArtifactContract,
    ArtifactRecord,
    PipelineDefinition,
    StageResult,
    StageSpec,
    deterministic_json,
)
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import ToolCapabilityRegistry
from docs.observability import ObservabilityPort

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


def _finding_code(message: str) -> str:
    """Recover a structured finding code from a human-readable stage message."""
    if message.startswith("[") and "]" in message:
        return message[1 : message.index("]")]
    return message


@dataclass(frozen=True)
class DocumentPipelineReport:
    """Stable report produced by the application-owned pipeline use case."""

    capabilities: dict[str, dict[str, str | bool | None]]
    execution: PipelineReport
    provenance: dict[str, Any] | None
    succeeded: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilities": self.capabilities,
            "execution": self.execution.to_dict(),
            "provenance": self.provenance,
            "succeeded": self.succeeded,
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_dict())


@dataclass(frozen=True)
class PublicationSpec:
    """The staged output contract for a publication operation."""

    expected_outputs: tuple[str, ...]
    destinations: tuple[Path, ...]
    operation: PublicationOperation


@dataclass(frozen=True)
class PipelineRequest:
    """Immutable instruction for one application-owned pipeline execution."""

    run_id: str
    inputs: tuple[Path, ...] = ()
    outputs: tuple[Path, ...] = ()
    publish: bool = True
    pipeline_id: str = "document"
    external_artifacts: tuple[str, ...] | None = None
    excluded_stages: frozenset[str] = frozenset()


StageOperationMap = Mapping[str, StageOperation]


class PipelineService:
    """Own document pipeline execution and its stable application report."""

    def __init__(
        self,
        *,
        operations: StageOperationMap,
        publication: PublicationSpec,
        capabilities: ToolCapabilityRegistry,
        ledger: ProvenanceLedger,
        atomic_transform: AtomicTransform,
        policy: PipelinePolicy | None = None,
        run_id_sink: Callable[[str], None] | None = None,
        excluded_stages: frozenset[str] = frozenset(),
        cleanup: Callable[[], None] | None = None,
        artifact_store: StageArtifactStore | None = None,
        record_sink: Callable[[tuple[ArtifactRecord, ...]], None] | None = None,
        run_start: Callable[[], None] | None = None,
        observability: ObservabilityPort | None = None,
        definition: PipelineDefinition | None = None,
    ) -> None:
        self._operations = operations
        self._publication = publication
        self._atomic_transform = atomic_transform
        self._capabilities = capabilities
        self._policy = policy
        self._ledger = ledger
        self._artifact_store = artifact_store
        self._record_sink = record_sink
        self._run_start = run_start
        self.registry = PipelineRegistry()
        custom_definition = definition is not None
        definition = definition or self._definition(excluded_stages)
        self._contracts = {contract.name: contract for contract in definition.artifacts}
        stage_names = {stage.name for stage in definition.stages}
        handlers = {name: handler for name, handler in self._handlers().items() if name in stage_names}
        self.registry.register("document", definition, handlers)
        if not custom_definition:
            self.registry.register_catalog(definition, handlers)
        registered = self.registry.resolve("document")
        self.planner = PipelinePlanner()
        self.definition = registered.definition
        self.stage_plan = self.planner.plan(self.definition)
        self._executors = {
            name: _PipelineExecutor(entry.definition, entry.handlers, observability)
            for name, entry in ((pipeline, self.registry.resolve(pipeline)) for pipeline in self.registry.names())
        }
        self._run_id_sink = run_id_sink
        self._cleanup = cleanup
        self._completion_artifacts: dict[Path, bytes | None] | None = None
        self._active_run_id = ""

    def execute(self, request: PipelineRequest) -> DocumentPipelineReport:
        """Execute one immutable request and return the established report."""
        run_id = request.run_id
        inputs = request.inputs
        publish = request.publish
        pipeline_id = request.pipeline_id
        external_artifacts = request.external_artifacts
        if pipeline_id not in self._executors:
            raise ValueError(f"pipeline is not registered: {pipeline_id}")
        if publish and pipeline_id not in {"document", "document-publish"}:
            raise ValueError("only the full document pipeline or document-publish pipeline may publish")
        if self._run_start is not None:
            self._run_start()
        succeeded = False
        self._completion_artifacts = {}
        self._active_run_id = run_id
        try:
            materialized_external = tuple(external_artifacts) if external_artifacts is not None else None
            definition = self.registry.resolve(pipeline_id).definition
            supplied_external = (
                definition.external_artifacts
                if materialized_external is None and pipeline_id == "document"
                else frozenset(materialized_external or ())
            )
            missing_external = sorted(definition.external_artifacts - supplied_external)
            if missing_external:
                return DocumentPipelineReport(
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
                        f"required capability unavailable: {name}" for name in missing_capabilities
                    )
                    results = [StageResult("capabilities", False, errors=capability_error)]
                    for stage_name in ("record-provenance", "package-release", "publish-draft"):
                        if stage_name in {stage.name for stage in definition.stages}:
                            results.append(StageResult(stage_name, False, errors=capability_error))
                    return DocumentPipelineReport(
                        capabilities=self._capabilities.report(),
                        execution=PipelineReport(tuple(results)),
                        provenance=None,
                        succeeded=False,
                    )
            if self._run_id_sink is not None:
                self._run_id_sink(run_id)
            excluded: frozenset[str] = request.excluded_stages | (
                frozenset()
                if publish
                else frozenset(
                    {"publish-draft"} | ({"package-release"} if pipeline_id != "document-package" else set())
                )
            )
            if not publish and run_id.startswith("cli-verify-"):
                excluded = excluded | frozenset({"record-provenance"})
            report = self._execute_registered(
                pipeline_id,
                run_id=run_id,
                inputs=inputs,
                outputs=(request.outputs or (self._publication.destinations if publish else ())),
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
                        if (result.stage in {"record-provenance", "package-release", "publish-draft"} and result.ok)
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
                    if stage.name not in {"package-release", "publish-draft"} or stage.name in executed:
                        continue
                    unavailable = tuple(artifact for artifact in stage.requires if artifact not in available)
                    publication_error = (
                        "required dependency unavailable: " + ", ".join(unavailable)
                        if unavailable
                        else "; ".join(
                            publication_block_errors
                            or ("required dependency unavailable: " + ", ".join(stage.requires),)
                        )
                    )
                    results.append(
                        StageResult(
                            stage.name,
                            False,
                            errors=(publication_error,),
                        )
                    )
                if len(results) != len(report.execution.results):
                    report = DocumentPipelineReport(
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
            self._active_run_id = ""
            if self._cleanup is not None:
                self._cleanup()

    def _execute_registered(
        self,
        pipeline_id: str,
        *,
        run_id: str,
        inputs: tuple[Path, ...],
        outputs: tuple[Path, ...],
        excluded_stages: frozenset[str],
        external_artifacts: frozenset[str],
    ) -> DocumentPipelineReport:
        """Apply run policy, execute one registered DAG, and assemble its report."""
        del inputs  # Input identities are recorded by the provenance stage itself.
        executor = self._executors[pipeline_id]
        definition = executor.definition
        capabilities = self._capabilities.report()
        missing_required = self._capabilities.missing_required()
        capability_evaluation = self._capabilities.evaluate(self._policy) if self._policy is not None else None
        if capability_evaluation is not None and capability_evaluation.blocking:
            results = [StageResult("capabilities", False, errors=capability_evaluation.errors)]
            if outputs:
                stage_names = {stage.name for stage in definition.stages}
                for stage_name in ("record-provenance", "package-release", "publish-draft"):
                    if stage_name in stage_names:
                        results.append(
                            StageResult(
                                stage_name,
                                False,
                                errors=("required capability unavailable: " + ", ".join(missing_required),),
                            )
                        )
            return DocumentPipelineReport(capabilities, PipelineReport(tuple(results)), None, False)

        policy_excluded_stages = set(excluded_stages)
        publish_disallowed = (
            self._policy is not None
            and not ({"publish", "publish-draft"} & set(excluded_stages))
            and not self._policy.can_publish()
        )
        capability_blocks_publication = bool(missing_required and outputs)
        if publish_disallowed or capability_blocks_publication:
            policy_excluded_stages.update({"publish-draft", "package-release"})

        stage_specs = {stage.name: stage for stage in definition.stages}

        def apply_policy(result: StageResult) -> StageResult:
            if self._policy is None:
                return result
            optional_gap = (
                result.outcome in {"unsupported", "skipped"}
                and stage_specs.get(result.stage) is not None
                and stage_specs[result.stage].optional
            )
            warnings = tuple(
                warning
                for warning in result.warnings
                if optional_gap or self._policy.severity(_finding_code(warning), "warning") == "warning"
            )
            errors = list(result.errors)
            for warning in result.warnings:
                if (
                    self._policy.severity(_finding_code(warning), "warning") == "error"
                    and not optional_gap
                    and warning not in errors
                ):
                    errors.append(warning)
            return StageResult(result.stage, not errors, result.artifacts, warnings, tuple(errors), result.outcome)

        execution = executor.run(
            excluded_stages=policy_excluded_stages,
            external_artifacts=set(external_artifacts),
            result_mapper=apply_policy,
            fail_on_unsupported=bool(outputs),
            block_publication_on_package_failure=(
                self._policy is not None and self._policy.mode in {PipelineMode.strict, PipelineMode.release}
            ),
        )
        results = list(execution.results)
        if self._policy is not None:
            package_failed = any(
                result.stage == "package-release" and (not result.ok or result.outcome != "succeeded")
                for result in results
            )
            if package_failed and self._policy.mode in {PipelineMode.strict, PipelineMode.release}:
                results = [
                    StageResult(
                        result.stage,
                        False,
                        result.artifacts,
                        result.warnings,
                        (*result.errors, "package-release failed; publication blocked"),
                    )
                    if result.stage == "publish-draft" and result.ok
                    else result
                    for result in results
                ]
            if capability_evaluation is not None and capability_evaluation.warnings:
                results.insert(
                    0,
                    StageResult("capabilities", True, warnings=capability_evaluation.warnings),
                )
            if publish_disallowed or capability_blocks_publication:
                errors = ["publish disallowed by pipeline policy"] if publish_disallowed else []
                if capability_blocks_publication:
                    errors.extend(f"required capability unavailable: {name}" for name in missing_required)
                results.append(StageResult("publish-draft", False, errors=tuple(errors)))
        execution = PipelineReport(tuple(results))
        succeeded = all(result.ok for result in execution.results)
        provenance = self._ledger.load_run(run_id) if succeeded else None
        return DocumentPipelineReport(capabilities, execution, provenance, succeeded)

    def _handlers(self) -> dict[str, StageHandler]:
        handlers: dict[str, StageHandler] = {"publish-draft": self._publish}
        for stage_name, operation in self._operations.items():
            handlers[stage_name] = self._adapt(
                stage_name,
                operation,
                f"{stage_name}-complete",
                artifact_root=(
                    self._publication.destinations[0].parent.parent if self._publication.destinations else None
                ),
                artifact_writer=self._write_completion_artifact,
                artifact_store=self._artifact_store,
                contract=self._contracts.get(f"{stage_name}-complete"),
                record_sink=self._record_sink,
                receipt_directory=self._receipt_directory,
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
        artifact_store: StageArtifactStore | None = None,
        contract: ArtifactContract | None = None,
        record_sink: Callable[[tuple[ArtifactRecord, ...]], None] | None = None,
        receipt_directory: Callable[[], str] | None = None,
    ) -> StageHandler:
        def handler() -> StageResult:
            raw = operation()
            if isinstance(raw, StageResult):
                result = raw
                detail = raw.to_json()
            else:
                ok, detail = raw
                result = StageResult(name, ok, errors=() if ok else (detail,))
            if result.ok and result.outcome == "succeeded" and not result.artifacts:
                if artifact_store is not None and contract is not None:
                    receipt = artifact_store.write_stage_receipt(
                        contract,
                        name,
                        detail,
                        relative_dir=receipt_directory() if receipt_directory is not None else "stages",
                    )
                    result = replace(result, artifacts=(receipt,))
                elif (
                    artifact_root is not None
                    and output_contract
                    in {
                        "accessibility-review-complete",
                        "reproducibility-check-complete",
                    }
                    and artifact_writer is not None
                ):
                    result = replace(result, artifacts=(artifact_writer(name, output_contract, detail),))
            if result.ok and result.outcome == "succeeded" and result.artifacts and record_sink is not None:
                record_sink(result.artifacts)
            return result

        return handler

    def _receipt_directory(self) -> str:
        return f"{self._active_run_id}/stages"

    def _write_completion_artifact(self, stage: str, contract: str, detail: str) -> ArtifactRecord:
        if not self._publication.destinations:
            raise RuntimeError("completion artifact publication root is unavailable")
        artifact_path = self._publication.destinations[0].parent.parent / "stages" / f"{contract}.json"
        if self._completion_artifacts is not None and artifact_path not in self._completion_artifacts:
            self._completion_artifacts[artifact_path] = artifact_path.read_bytes() if artifact_path.is_file() else None
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
                        str(destination),
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
            "compose-cover": ("generate-visuals-complete",),
            "build-docx": ("compose-cover-complete",),
            "build-html": ("build-docx-complete",),
            "build-pdf": ("build-docx-complete",),
            "structural-audit": ("build-docx-complete",),
            "editorial-review": ("structural-audit-complete",),
            "evidence-review": ("structural-audit-complete",),
            "consistency-review": ("structural-audit-complete",),
            "accessibility-review": ("structural-audit-complete",),
            "visual-review": ("structural-audit-complete",),
            "reproducibility-check": ("structural-audit-complete",),
            "record-provenance": tuple(
                f"{name}-complete"
                for name in (
                    "editorial-review",
                    "evidence-review",
                    "consistency-review",
                    "accessibility-review",
                    "visual-review",
                    "reproducibility-check",
                )
            ),
            "package-release": ("record-provenance-complete", "editorial-review-complete"),
            "publish-draft": ("record-provenance-complete", "editorial-review-complete"),
        }
        dependencies = {
            stage_name: tuple(artifact for artifact in required_artifacts)
            for stage_name, required_artifacts in dependencies.items()
            if stage_name in stage_ids
        }
        dependency_artifacts = {artifact for stage_name in stage_ids for artifact in dependencies.get(stage_name, ())}
        artifact_names = {f"{stage_name}-complete" for stage_name in stage_ids} | dependency_artifacts
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
