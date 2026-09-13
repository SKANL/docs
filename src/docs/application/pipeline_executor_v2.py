"""Execution engine for the pipeline kernel contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from time import perf_counter
from typing import Protocol

from docs.domain.pipeline_kernel import PipelineDefinition, StageResult, deterministic_json


class StageHandler(Protocol):
    """Callable implementation for one planned pipeline stage."""

    def __call__(self) -> StageResult: ...


class PipelineReport:
    """Immutable-in-practice, ordered execution results."""

    def __init__(self, results: tuple[StageResult, ...] = ()) -> None:
        self.results = results

    def to_dict(self) -> dict[str, object]:
        # Timing is execution metadata, not part of the stable report schema.
        # Keep the report byte-stable while exposing duration_ms on each result
        # for callers that need runtime telemetry.
        return {
            "results": [
                {key: value for key, value in result.to_dict().items() if key != "duration_ms"}
                for result in self.results
            ]
        }

    def to_json(self) -> str:
        return deterministic_json(self.to_dict())


class PipelineExecutor:
    def __init__(
        self,
        definition: PipelineDefinition,
        handlers: Mapping[str, StageHandler],
    ) -> None:
        self.definition = definition
        self.handlers = handlers

    def run(
        self,
        *,
        excluded_stages: set[str] | frozenset[str] = frozenset(),
        result_mapper: Callable[[StageResult], StageResult] | None = None,
        fail_on_unsupported: bool = False,
        block_publication_on_package_failure: bool = False,
    ) -> PipelineReport:
        stages = {stage.name: stage for stage in self.definition.stages}
        producers = {
            artifact: stage.name
            for stage in self.definition.stages
            for artifact in stage.produces
        }
        required_artifacts = {
            contract.name for contract in self.definition.artifacts if contract.required
        }
        results: list[StageResult] = []
        unavailable_artifacts: set[str] = set()
        for stage_name in self.definition.plan():
            if stage_name in excluded_stages:
                unavailable_artifacts.update(stages[stage_name].produces)
                continue
            stage = stages[stage_name]
            unavailable_dependencies = tuple(
                artifact for artifact in stage.requires if artifact in unavailable_artifacts
            )
            if unavailable_dependencies:
                unavailable_artifacts.update(stage.produces)
                results.append(
                    StageResult(
                        stage_name,
                        False,
                        errors=(
                            "required dependency unavailable: "
                            + ", ".join(unavailable_dependencies),
                        ),
                    )
                )
                continue
            if block_publication_on_package_failure and stage_name == "publish-draft" and any(
                result.stage == "package-release"
                and (not result.ok or result.outcome != "succeeded")
                for result in results
            ):
                unavailable_artifacts.update(stage.produces)
                results.append(
                    StageResult(
                        stage_name,
                        False,
                        errors=("required dependency unavailable: package-release",),
                    )
                )
                continue
            handler = self.handlers.get(stage_name)
            started = perf_counter()
            try:
                result = StageResult.unsupported(stage_name) if handler is None else handler()
            except Exception as exc:
                result = StageResult(stage_name, False, errors=(f"stage handler failed: {exc}",))
            result = replace(result, duration_ms=max(0, round((perf_counter() - started) * 1000)))
            if (
                result.outcome == "unsupported"
                and fail_on_unsupported
                and not stage.optional
            ):
                result = StageResult(stage_name, False, errors=(f"stage unsupported: {stage_name}",))
            if result.stage != stage_name:
                raise ValueError(
                    f"Handler for stage {stage_name!r} returned result for {result.stage!r}"
                )
            if result_mapper is not None:
                result = result_mapper(result)
            declared = set(stage.produces)
            reported = {artifact.contract for artifact in result.artifacts}
            undeclared = sorted(reported - declared)
            missing_required = sorted(required_artifacts.intersection(declared) - reported)
            if result.ok and result.outcome == "succeeded" and (undeclared or missing_required):
                result = StageResult(
                    stage_name,
                    False,
                    result.artifacts,
                    result.warnings,
                    tuple(result.errors)
                    + tuple(f"undeclared artifact produced: {artifact}" for artifact in undeclared)
                    + tuple(
                        f"required declared artifact missing: {artifact}"
                        for artifact in missing_required
                    ),
                )
            results.append(result)
            unavailable = not result.ok or (
                result.outcome == "unsupported"
                and (
                    not stage.optional
                    or bool(required_artifacts.intersection(stage.produces))
                    or stage.name == "package-release"
                )
            )
            if unavailable:
                unavailable_artifacts.update(
                    artifact for artifact, producer in producers.items() if producer == stage_name
                )
            if not result.ok and stage.fail_fast and not stage.optional:
                break
        return PipelineReport(tuple(results))
