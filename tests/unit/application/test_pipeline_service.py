# tests/unit/application/test_pipeline_service.py
"""Unit coverage for PipelineService (document-pipeline spec: `Application-
Layer Test Coverage`). Constructs the service with a fake evidence
repository and inert placeholders for the collaborators a given method does
not touch -- exercises `rules_manifest_state` in isolation, distinct from
the repository-backed integration coverage in
tests/integration/test_pipeline_service.py."""
from __future__ import annotations

from pathlib import Path

from docs.application.pipeline import PipelineService


class _FakeEvidenceRepository:
    def file_exists(self, path: Path) -> bool:
        return True

    def file_size(self, path: Path) -> int:
        return 42


def _service(evidence_repository) -> PipelineService:
    unused = object()
    return PipelineService(
        doctor_service=unused,
        evidence_service=unused,
        evidence_repository=evidence_repository,
        collection_service=unused,
        source_repository=unused,
        review_service=unused,
        context_pack_service=unused,
        context_repository=unused,
        docx_assembly_service=unused,
        format_audit_service=unused,
        qa_service=unused,
        workspace=unused,
        ingest_service=unused,
    )


def test_rules_manifest_state_reads_existence_and_size_through_the_repository():
    service = _service(_FakeEvidenceRepository())

    exists, size = service.rules_manifest_state({"paths": {"rules_manifest": "whatever.json"}})

    assert (exists, size) == (True, 42)


def test_rules_manifest_state_skips_size_lookup_when_manifest_absent():
    class _AbsentRepo(_FakeEvidenceRepository):
        def file_exists(self, path: Path) -> bool:
            return False

        def file_size(self, path: Path) -> int:
            raise AssertionError("file_size must not be called when the manifest is absent")

    service = _service(_AbsentRepo())

    exists, size = service.rules_manifest_state({"paths": {"rules_manifest": "missing.json"}})

    assert (exists, size) == (False, 0)
