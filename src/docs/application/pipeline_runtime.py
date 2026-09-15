"""Facade for executing v2 pipelines with capabilities and provenance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.pipeline_executor import PipelineExecutor, PipelineReport, StageHandler
from docs.application.provenance import ProvenanceLedger
from docs.domain.pipeline_kernel import PipelineDefinition, StageResult, deterministic_json
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.tool_capability import ToolCapabilityRegistry


def _finding_code(message: str) -> str:
    """Recover a structured finding code from a human-readable stage message."""
    if message.startswith("[") and "]" in message:
        return message[1:message.index("]")]
    return message


@dataclass(frozen=True)
class PipelineRuntimeReport:
    """Stable execution, capability, and provenance report for one pipeline run."""

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


class PipelineRuntime:
    """Run one pipeline definition and record provenance only after success."""

    def __init__(
        self,
        definition: PipelineDefinition,
        handlers: Mapping[str, StageHandler],
        capabilities: ToolCapabilityRegistry,
        ledger: ProvenanceLedger,
        policy: PipelinePolicy | None = None,
    ) -> None:
        self._executor = PipelineExecutor(definition, handlers)
        self._capabilities = capabilities
        self._ledger = ledger
        self._policy = policy

    def run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path] = (),
        outputs: Iterable[Path] = (),
        excluded_stages: set[str] | frozenset[str] = frozenset(),
        external_artifacts: Iterable[str] | None = None,
    ) -> PipelineRuntimeReport:
        """Execute the pipeline and persist hashes only when every stage succeeds."""
        output_paths = tuple(outputs)
        capabilities = self._capabilities.report()
        missing_required = self._capabilities.missing_required()
        capability_evaluation = self._capabilities.evaluate(self._policy) if self._policy is not None else None
        if capability_evaluation is not None and capability_evaluation.blocking:
            results = [StageResult("capabilities", False, errors=capability_evaluation.errors)]
            if output_paths:
                stage_names = {stage.name for stage in self._executor.definition.stages}
                for stage_name in ("record-provenance", "package-release", "publish-draft"):
                    if stage_name in stage_names:
                        results.append(
                            StageResult(
                                stage_name,
                                False,
                                errors=(
                                    "required capability unavailable: "
                                    + ", ".join(self._capabilities.missing_required()),
                                ),
                            )
                        )
            execution = PipelineReport(tuple(results))
            return PipelineRuntimeReport(capabilities=capabilities, execution=execution, provenance=None, succeeded=False)

        policy_excluded_stages = set(excluded_stages)
        publish_disallowed = (
            self._policy is not None
            and not ({"publish", "publish-draft"} & set(excluded_stages))
            and not self._policy.can_publish()
        )
        capability_blocks_publication = bool(missing_required and output_paths)
        if publish_disallowed or capability_blocks_publication:
            policy_excluded_stages.update({"publish-draft", "package-release"})
        def apply_policy(result: StageResult) -> StageResult:
            if self._policy is None:
                return result
            stage_specs = {stage.name: stage for stage in self._executor.definition.stages}
            warnings = tuple(
                warning
                for warning in result.warnings
                if (
                    warning.startswith("stage unsupported:")
                    and stage_specs.get(result.stage) is not None
                    and stage_specs[result.stage].optional
                )
                or (
                    warning.startswith("stage skipped:")
                    and stage_specs.get(result.stage) is not None
                    and stage_specs[result.stage].optional
                )
                or self._policy.severity(_finding_code(warning), "warning") == "warning"
            )
            errors = tuple(result.errors) + tuple(
                warning
                for warning in result.warnings
                if self._policy.severity(_finding_code(warning), "warning") == "error"
                and not (
                    (
                        warning.startswith("stage unsupported:")
                        or warning.startswith("stage skipped:")
                    )
                    and stage_specs.get(result.stage) is not None
                    and stage_specs[result.stage].optional
                )
            )
            return StageResult(result.stage, not errors, result.artifacts, warnings, errors, result.outcome)

        executor_external_artifacts = set(external_artifacts or ())
        execution = self._executor.run(
            excluded_stages=policy_excluded_stages,
            external_artifacts=executor_external_artifacts,
            result_mapper=apply_policy,
            fail_on_unsupported=bool(output_paths),
            block_publication_on_package_failure=(
                self._policy is not None
                and self._policy.mode in {PipelineMode.strict, PipelineMode.release}
            ),
        )
        if self._policy is not None:
            results = list(execution.results)
            package_failed = any(
                result.stage == "package-release"
                and (not result.ok or result.outcome != "succeeded")
                for result in results
            )
            if package_failed and self._policy.mode in {PipelineMode.strict, PipelineMode.release}:
                results = [
                    (
                        StageResult(
                            result.stage,
                            False,
                            result.artifacts,
                            result.warnings,
                            (*result.errors, "package-release failed; publication blocked"),
                        )
                        if result.stage == "publish-draft" and result.ok
                        else result
                    )
                    for result in results
                ]
            if capability_evaluation is not None and capability_evaluation.warnings:
                results.insert(
                    0,
                    StageResult(
                        stage="capabilities",
                        ok=True,
                        warnings=capability_evaluation.warnings,
                    ),
                )
            if publish_disallowed or capability_blocks_publication:
                errors: list[str] = []
                if publish_disallowed:
                    errors.append("publish disallowed by pipeline policy")
                if capability_blocks_publication:
                    errors.extend(
                        f"required capability unavailable: {name}"
                        for name in missing_required
                    )
                results.append(
                    StageResult(
                        stage="publish-draft",
                        ok=False,
                        errors=tuple(errors),
                    )
                )
            execution = PipelineReport(tuple(results))
        succeeded = all(result.ok for result in execution.results)
        provenance = None
        if succeeded:
            provenance = self._ledger.load_run(run_id)
        return PipelineRuntimeReport(
            capabilities=capabilities,
            execution=execution,
            provenance=provenance,
            succeeded=succeeded,
        )
