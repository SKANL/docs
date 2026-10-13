"""Execution engine for the pipeline kernel contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Protocol

from docs.domain.pipeline_kernel import (
    PipelineDefinition,
    StageResult,
    StageSpec,
    deterministic_json,
)
from docs.observability import NoOpObservability, ObservabilityPort


@contextmanager
def _fail_open_span(span_factory: Callable[[], Any]) -> Iterator[None]:
    """Close telemetry with the real exception triple without affecting stages."""
    try:
        context = span_factory()
    except Exception:
        context = nullcontext()
    entered = False
    try:
        try:
            context.__enter__()
            entered = True
        except Exception as exc:
            with suppress(Exception):
                context.__exit__(type(exc), exc, exc.__traceback__)
            yield
            return
        try:
            yield
        except BaseException as exc:
            if entered:
                with suppress(Exception):
                    context.__exit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            if entered:
                with suppress(Exception):
                    context.__exit__(None, None, None)
    except BaseException:
        raise


def _stage_span_factory(observability: ObservabilityPort, stage_name: str) -> Callable[[], Any]:
    def factory() -> Any:
        return observability.span("docs.pipeline.stage", {"stage": stage_name})

    return factory


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


@dataclass
class _RunState:
    """Mutable bookkeeping for one pipeline run."""

    results: list[StageResult] = field(default_factory=list)
    unavailable_artifacts: set[str] = field(default_factory=set)
    unavailable_stages: set[str] = field(default_factory=set)
    halted: bool = False

    def mark_unavailable(self, stage: StageSpec) -> None:
        self.unavailable_stages.add(stage.name)
        self.unavailable_artifacts.update(stage.produces)


class _PipelineExecutor:
    def __init__(
        self,
        definition: PipelineDefinition,
        handlers: Mapping[str, StageHandler],
        observability: ObservabilityPort | None = None,
    ) -> None:
        self.definition = definition
        self.handlers = handlers
        self.observability = observability or NoOpObservability()

    def run(
        self,
        *,
        excluded_stages: set[str] | frozenset[str] = frozenset(),
        external_artifacts: set[str] | frozenset[str] | None = None,
        result_mapper: Callable[[StageResult], StageResult] | None = None,
        fail_on_unsupported: bool = False,
        block_publication_on_package_failure: bool = False,
    ) -> PipelineReport:
        missing_external = sorted(self.definition.external_artifacts - set(external_artifacts or ()))
        if missing_external:
            return PipelineReport((_external_prerequisites_failure(missing_external),))
        stages = {stage.name: stage for stage in self.definition.stages}
        producers = {artifact: stage.name for stage in self.definition.stages for artifact in stage.produces}
        state = _RunState()
        for stage_name in self.definition.plan():
            stage = stages[stage_name]
            if stage_name in excluded_stages:
                state.mark_unavailable(stage)
                continue
            if self._skip_stage(stage, state, block_publication_on_package_failure):
                continue
            result = self._execute_stage(stage, fail_on_unsupported, result_mapper)
            result = self._enforce_artifact_contracts(stage, result)
            state.results.append(result)
            self._emit_stage_metrics(stage_name, result)
            if self._is_unavailable(stage, result):
                state.unavailable_stages.add(stage_name)
                state.unavailable_artifacts.update(
                    artifact for artifact, producer in producers.items() if producer == stage_name
                )
                if stage.fail_fast and not stage.optional:
                    state.halted = True
        return PipelineReport(tuple(state.results))

    def _skip_stage(
        self, stage: StageSpec, state: _RunState, block_publication_on_package_failure: bool
    ) -> bool:
        """Record a skip or dependency failure for a stage that must not run."""
        unavailable_predecessors = tuple(p for p in stage.after if p in state.unavailable_stages)
        unavailable_dependencies = tuple(a for a in stage.requires if a in state.unavailable_artifacts)
        if unavailable_predecessors or unavailable_dependencies:
            state.mark_unavailable(stage)
            state.results.append(
                StageResult(
                    stage.name,
                    False,
                    errors=(
                        "required dependency unavailable: "
                        + ", ".join(unavailable_dependencies or unavailable_predecessors),
                    ),
                )
            )
            return True
        if state.halted:
            state.mark_unavailable(stage)
            return True
        if (
            block_publication_on_package_failure
            and stage.name == "publish-draft"
            and any(
                result.stage == "package-release" and (not result.ok or result.outcome != "succeeded")
                for result in state.results
            )
        ):
            state.unavailable_artifacts.update(stage.produces)
            state.results.append(
                StageResult(
                    stage.name,
                    False,
                    errors=("required dependency unavailable: package-release",),
                )
            )
            return True
        return False

    def _execute_stage(
        self,
        stage: StageSpec,
        fail_on_unsupported: bool,
        result_mapper: Callable[[StageResult], StageResult] | None,
    ) -> StageResult:
        handler = self.handlers.get(stage.name)
        started = perf_counter()
        try:
            with _fail_open_span(_stage_span_factory(self.observability, stage.name)):
                result = StageResult.unsupported(stage.name) if handler is None else handler()
        except Exception as exc:
            result = StageResult(stage.name, False, errors=(f"stage handler failed: {exc}",))
        result = replace(
            result,
            duration_ms=result.duration_ms
            if result.duration_ms is not None
            else max(0, round((perf_counter() - started) * 1000)),
        )
        if result.outcome == "unsupported" and fail_on_unsupported and not stage.optional:
            result = replace(
                result,
                ok=False,
                outcome="failed",
                errors=(*result.errors, f"stage unsupported: {stage.name}"),
            )
        if result.stage != stage.name:
            raise ValueError(f"Handler for stage {stage.name!r} returned result for {result.stage!r}")
        if result_mapper is not None:
            result = result_mapper(result)
        return result

    def _enforce_artifact_contracts(self, stage: StageSpec, result: StageResult) -> StageResult:
        """Fail a successful result whose artifacts break the declared contracts."""
        declared = set(stage.produces)
        reported = {artifact.contract for artifact in result.artifacts}
        undeclared = sorted(reported - declared)
        missing_required = sorted(self._required_artifacts().intersection(declared) - reported)
        contracts = {contract.name: contract for contract in self.definition.artifacts}
        contract_errors: list[str] = []
        for record in result.artifacts:
            if record.contract not in declared:
                continue
            contract = contracts.get(record.contract)
            if contract is None:
                continue
            try:
                contract.validate_record(record)
            except ValueError as exc:
                contract_errors.append(f"artifact {record.contract} does not satisfy its contract: {exc}")
        if result.ok and result.outcome == "succeeded" and (undeclared or missing_required or contract_errors):
            return StageResult(
                stage.name,
                False,
                result.artifacts,
                result.warnings,
                tuple(result.errors)
                + tuple(f"undeclared artifact produced: {artifact}" for artifact in undeclared)
                + tuple(f"required declared artifact missing: {artifact}" for artifact in missing_required)
                + tuple(contract_errors),
                duration_ms=result.duration_ms,
            )
        return result

    def _emit_stage_metrics(self, stage_name: str, result: StageResult) -> None:
        # Emit only after result mapping and artifact validation have
        # established the final status visible to pipeline consumers.
        with suppress(Exception):
            self.observability.increment(
                "docs.pipeline.stage.completed",
                attributes={"stage": stage_name, "outcome": result.outcome},
            )
            self.observability.observe(
                "docs.pipeline.stage.duration_ms",
                result.duration_ms or 0,
                {"stage": stage_name},
            )

    def _is_unavailable(self, stage: StageSpec, result: StageResult) -> bool:
        """Whether downstream stages must treat this stage's outputs as missing."""
        return not result.ok or (
            result.outcome == "unsupported"
            and (
                not stage.optional
                or bool(self._required_artifacts().intersection(stage.produces))
                or stage.name == "package-release"
            )
        )

    def _required_artifacts(self) -> set[str]:
        return {contract.name for contract in self.definition.artifacts if contract.required}


def _external_prerequisites_failure(missing: list[str]) -> StageResult:
    return StageResult(
        "external-prerequisites",
        False,
        errors=tuple(f"required external artifact unavailable: {artifact}" for artifact in missing),
    )
