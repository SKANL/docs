from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docs.application.atomic_transform_v2 import AtomicTransform
from docs.application.pipeline_service_v2 import FULL_STAGE_IDS, PipelineServiceV2, PublicationSpec
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.pipeline_kernel import ArtifactRecord, StageResult
from docs.domain.tool_capability import ToolCapabilityRegistry

TRACEABILITY_TEST = (
    "tests/integration/test_v2_full_stage_execution.py::"
    "test_full_stage_inventory_executes_explicit_operations_in_order_through_quality_gates"
)


def test_full_stage_inventory_executes_explicit_operations_in_order_through_quality_gates(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    destination = tmp_path / "published" / "document.txt"

    def operation(stage: str):
        def run() -> tuple[bool, str]:
            calls.append(stage)
            return True, f"{stage} completed"

        return run

    def publish_draft() -> StageResult:
        calls.append("publish-draft")
        content = b"published document\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return StageResult(
            "publish-draft",
            True,
            artifacts=(
                ArtifactRecord(
                    "publish-draft-complete",
                    str(destination),
                    hashlib.sha256(content).hexdigest(),
                    producer_stage="publish-draft",
                ),
            ),
        )

    operations = {stage: operation(stage) for stage in FULL_STAGE_IDS}
    operations["publish-draft"] = publish_draft
    service = PipelineServiceV2(
        operations=operations,
        publication=PublicationSpec(
            expected_outputs=("document.txt",),
            destinations=(destination,),
            operation=lambda scratch: None,
        ),
        capabilities=ToolCapabilityRegistry(()),
        ledger=ProvenanceLedgerV2(tmp_path / "provenance.json"),
        atomic_transform=AtomicTransform(),
    )

    report = service.run("all-explicit-stages")

    assert calls == list(FULL_STAGE_IDS)
    assert [result.stage for result in report.execution.results] == list(FULL_STAGE_IDS)
    assert report.succeeded is True
    assert all(result.ok and result.outcome == "succeeded" for result in report.execution.results)
    results = {result.stage: result for result in report.execution.results}
    assert results["record-provenance"].ok is True
    assert results["package-release"].ok is True
    assert results["publish-draft"].ok is True

    traceability = json.loads(
        (Path(__file__).parents[2] / "docs" / "migration-v2-traceability.json").read_text(
            encoding="utf-8"
        )
    )
    entries = {entry["stage"]: entry for entry in traceability["pipeline_stages"]}
    assert set(entries) == set(FULL_STAGE_IDS)
    assert all(
        entry["executable_evidence"] == {"status": "covered", "test": TRACEABILITY_TEST}
        and entry["observed_outcome"] == {"status": "succeeded", "test": TRACEABILITY_TEST}
        for entry in entries.values()
    )