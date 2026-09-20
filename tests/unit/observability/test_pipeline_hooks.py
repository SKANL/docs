from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal

from docs.application.pipeline_executor import PipelineExecutor
from docs.domain.pipeline_kernel import ArtifactContract, ArtifactRecord, PipelineDefinition, StageResult, StageSpec
from docs.observability import Observability


def test_pipeline_executor_emits_low_cardinality_stage_hooks():
    events: list[tuple[str, str, dict[str, str]]] = []
    telemetry = Observability(
        increment_hook=lambda name, value, attrs: events.append(("metric", name, attrs)),
        span_hook=lambda name, attrs: events.append(("span", name, attrs)),
    )
    definition = PipelineDefinition(stages=(StageSpec("build-docx"),))

    report = PipelineExecutor(
        definition,
        {"build-docx": lambda: StageResult("build-docx", True)},
        observability=telemetry,
    ).run()

    assert report.results[0].ok
    assert ("metric", "docs.pipeline.stage.completed", {"stage": "build-docx", "outcome": "succeeded"}) in events
    assert ("span", "docs.pipeline.stage", {"stage": "build-docx"}) in events


def test_unsupported_conversion_preserves_result_metadata_and_telemetry_failure_is_ignored():
    result = StageResult.unsupported("build-docx")
    telemetry = Observability(
        increment_hook=lambda *args: (_ for _ in ()).throw(RuntimeError("down")),
        observe_hook=lambda *args: (_ for _ in ()).throw(RuntimeError("down")),
        span_hook=lambda *args: (_ for _ in ()).throw(RuntimeError("down")),
    )
    definition = PipelineDefinition(stages=(StageSpec("build-docx"),))

    report = PipelineExecutor(
        definition,
        {"build-docx": lambda: result},
        observability=telemetry,
    ).run(fail_on_unsupported=True)

    converted = report.results[0]
    assert converted.outcome == "failed"
    assert converted.artifacts == result.artifacts
    assert converted.warnings == result.warnings
    assert converted.duration_ms is not None


def test_handler_failure_closes_span_with_exception_and_returns_stage_result():
    closed: list[tuple[type[BaseException] | None, BaseException | None, object]] = []

    class Span(AbstractContextManager[object]):
        def __enter__(self) -> object:
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> Literal[False]:
            closed.append((exc_type, exc_value, traceback))
            return False

    definition = PipelineDefinition(stages=(StageSpec("build-docx"),))

    report = PipelineExecutor(
        definition,
        {"build-docx": lambda: (_ for _ in ()).throw(RuntimeError("handler down"))},
        observability=Observability(span_hook=lambda _name, _attrs: Span()),
    ).run()

    assert not report.results[0].ok
    assert report.results[0].errors == ("stage handler failed: handler down",)
    assert len(closed) == 1
    exc_type, exc_value, traceback = closed[0]
    assert exc_type is RuntimeError
    assert str(exc_value) == "handler down"
    assert traceback is not None


def test_stage_success_telemetry_uses_status_after_contract_validation():
    events: list[tuple[str, dict[str, str]]] = []
    telemetry = Observability(
        increment_hook=lambda name, _value, attrs: events.append((name, attrs)),
    )
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("output", expected_path=Path("expected")),),
        stages=(StageSpec("build-docx", produces=("output",)),),
    )
    invalid_record = ArtifactRecord("output", "wrong", "abc")

    report = PipelineExecutor(
        definition,
        {"build-docx": lambda: StageResult("build-docx", True, artifacts=(invalid_record,))},
        observability=telemetry,
    ).run()

    assert not report.results[0].ok
    assert ("docs.pipeline.stage.completed", {"stage": "build-docx", "outcome": "failed"}) in events


def test_contract_validation_preserves_duration_and_all_result_metadata():
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("output", expected_path=Path("expected")),),
        stages=(StageSpec("build-docx", produces=("output",)),),
    )
    invalid_record = ArtifactRecord("output", "wrong", "abc")
    original = StageResult("build-docx", True, (invalid_record,), ("warning",), (), duration_ms=42)
    report = PipelineExecutor(definition, {"build-docx": lambda: original}).run()
    result = report.results[0]
    assert result.duration_ms == 42
    assert result.warnings == ("warning",)
    assert result.artifacts == (invalid_record,)
