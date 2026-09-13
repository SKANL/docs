from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docs.application.pipeline_components_v2 import (
    ArtifactStore,
    PipelinePlanner,
    PipelineRegistry,
    Publication,
    PublicationTransaction,
    RunReporter,
)
from docs.domain.pipeline_kernel import ArtifactContract, PipelineDefinition, StageResult, StageSpec


def test_registry_resolves_a_validated_definition_with_its_handlers() -> None:
    definition = PipelineDefinition(stages=(StageSpec("render"),))

    def handler() -> StageResult:
        return StageResult("render", True)

    registry = PipelineRegistry()

    registry.register("document", definition, {"render": handler})

    registered = registry.resolve("document")

    assert registered.definition is definition
    assert registered.handlers["render"] is handler
    with pytest.raises(ValueError, match="already registered"):
        registry.register("document", definition, {})


def test_planner_returns_stage_specs_in_dependency_order() -> None:
    definition = PipelineDefinition(
        artifacts=(ArtifactContract("rendered"),),
        stages=(
            StageSpec("publish", requires=("rendered",)),
            StageSpec("render", produces=("rendered",)),
        ),
    )

    plan = PipelinePlanner().plan(definition)

    assert tuple(stage.name for stage in plan) == ("render", "publish")


def test_artifact_store_writes_a_contract_bound_record(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    record = store.write(
        ArtifactContract("report", "text/plain"),
        "draft/report.txt",
        b"document body",
        metadata={"format": "txt"},
    )

    assert (tmp_path / "draft" / "report.txt").read_bytes() == b"document body"
    assert record.contract == "report"
    assert record.path == "draft/report.txt"
    assert record.sha256 == hashlib.sha256(b"document body").hexdigest()
    assert record.metadata == {"format": "txt"}


def test_publication_transaction_publishes_all_requested_artifacts(tmp_path: Path) -> None:
    report = tmp_path / "published" / "report.txt"
    manifest = tmp_path / "published" / "manifest.json"

    result = PublicationTransaction().publish(
        (
            Publication("report.txt", report, b"document body"),
            Publication("manifest.json", manifest, b'{"ok":true}'),
        )
    )

    assert result.ok is True
    assert result.outputs == (report, manifest)
    assert report.read_bytes() == b"document body"
    assert manifest.read_bytes() == b'{"ok":true}'


def test_run_reporter_preserves_ordered_stage_results_in_a_stable_report() -> None:
    report = RunReporter().report(
        (StageResult("render", True), StageResult("publish", False, errors=("blocked",)))
    )

    assert report.to_json() == (
        '{"results":[{"artifacts":[],"errors":[],"ok":true,"outcome":"succeeded",'
        '"stage":"render","warnings":[]},{"artifacts":[],"errors":["blocked"],'
        '"ok":false,"outcome":"failed","stage":"publish","warnings":[]}]}'
    )
