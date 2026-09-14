import json
from pathlib import Path

import pytest

from docs.domain.pipeline_kernel import (
    ArtifactContract,
    ArtifactRecord,
    CycleError,
    PipelineDefinition,
    StageResult,
    StageSpec,
    deterministic_json,
)


def test_contracts_and_records_serialize_deterministically():
    contract = ArtifactContract("manifest", "application/json", required=True)
    record = ArtifactRecord(contract="manifest", path="out/manifest.json", sha256="abc", metadata={"z": 2, "a": 1})

    assert deterministic_json(record) == deterministic_json(
        ArtifactRecord(contract="manifest", path="out/manifest.json", sha256="abc", metadata={"a": 1, "z": 2})
    )
    assert json.loads(deterministic_json(contract))["required"] is True


@pytest.mark.parametrize("size_bytes", [1.5, "12", True, [], {}])
def test_artifact_record_rejects_invalid_size_bytes_at_construction(size_bytes):
    with pytest.raises(ValueError, match="size_bytes"):
        ArtifactRecord("manifest", "out/manifest.json", "abc", size_bytes=size_bytes)


def test_pipeline_validates_contracts_and_returns_topological_plan():
    pipeline = PipelineDefinition(
        artifacts=(ArtifactContract("source"), ArtifactContract("rendered")),
        stages=(
            StageSpec("render", requires=("source",), produces=("rendered",)),
            StageSpec("ingest", produces=("source",)),
        ),
    )

    assert pipeline.plan() == ("ingest", "render")
    pipeline.validate()


def test_pipeline_rejects_missing_artifact_contract():
    pipeline = PipelineDefinition(stages=(StageSpec("render", produces=("missing",)),))

    with pytest.raises(ValueError, match="missing"):
        pipeline.validate()


def test_pipeline_rejects_required_artifact_without_a_producer():
    pipeline = PipelineDefinition(
        artifacts=(ArtifactContract("manifest", required=True),),
    )

    with pytest.raises(ValueError, match=r"required artifact.*producer.*manifest"):
        pipeline.validate()


def test_pipeline_detects_cycles():
    pipeline = PipelineDefinition(
        artifacts=(ArtifactContract("a"), ArtifactContract("b")),
        stages=(
            StageSpec("first", requires=("b",), produces=("a",)),
            StageSpec("second", requires=("a",), produces=("b",)),
        ),
    )

    with pytest.raises(CycleError, match=r"first|second"):
        pipeline.plan()


def test_stage_result_round_trips_as_stable_data():
    result = StageResult("ingest", ok=True, artifacts=(ArtifactRecord("source", "source.md", "abc"),), warnings=("late",))

    assert json.loads(deterministic_json(result)) == {
        "artifacts": [{"contract": "source", "metadata": {}, "path": "source.md", "sha256": "abc"}],
        "errors": [],
        "ok": True,
        "outcome": "succeeded",
        "stage": "ingest",
        "warnings": ["late"],
    }


def test_failed_stage_result_serializes_a_failed_outcome():
    result = StageResult("ingest", ok=False, errors=("ingest failed",))

    assert json.loads(result.to_json())["outcome"] == "failed"


def test_artifact_contract_and_record_expose_reproducible_contract_metadata():
    contract = ArtifactContract(
        "rendered",
        "application/pdf",
        required=True,
        source_inputs=("sections/001.md",),
        expected_path=Path("output/rendered.pdf"),
        deterministic=False,
        reopen_check="pdfium",
    )
    record = ArtifactRecord(
        "rendered",
        "output/rendered.pdf",
        "a" * 64,
        media_type="application/pdf",
        size_bytes=42,
        state="verified",
        producer_stage="build-pdf",
        run_id="run-1",
    )

    payload = json.loads(deterministic_json({"contract": contract, "record": record}))

    assert payload["contract"]["expected_path"] == "output/rendered.pdf"
    assert payload["contract"]["source_inputs"] == ["sections/001.md"]
    assert record.artifact_id == "rendered"
    assert payload["record"]["producer_stage"] == "build-pdf"


def test_artifact_contract_rejects_non_string_record_paths_with_actionable_error():
    contract = ArtifactContract("rendered", expected_path=Path("output/rendered.pdf"))
    record = ArtifactRecord("rendered", 123, "a" * 64)

    with pytest.raises(ValueError, match=r"path.*string"):
        contract.validate_record(record)
