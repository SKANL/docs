from pathlib import Path

import pytest

from docs.application.pipeline_publication import PipelinePublication
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest


def _manifest(*, passed: bool = True) -> BuildManifest:
    return BuildManifest(
        document_id="report",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"docx": "test"},
        artifacts=(ArtifactRef("report.docx", "e" * 64, ArtifactState.READY),),
        verification={"passed": passed},
        provenance_run="run-1",
    )


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def record_run(self, run_id, *, inputs, outputs):
        self.calls.append("run")

    def record_attestation(self, run_id, manifest):
        self.calls.append("attestation")

    def verify_attestation(self, run_id, manifest):
        return True


class _ManifestService:
    def create_manifest(self, **kwargs):
        return _manifest(passed=kwargs["verification"]["passed"])

    def record_provenance(self, ledger, run_id, root, artifact, manifest):
        ledger.record_run(run_id, inputs=(), outputs=(artifact,))
        ledger.record_attestation(run_id, manifest.attestation())

    def write_manifest(self, manifest, destination):
        destination.write_text(manifest.to_json() + "\n", encoding="utf-8")


def test_records_provenance_only_after_manifest_is_publishable(tmp_path: Path) -> None:
    ledger = _Ledger()
    boundary = PipelinePublication(_ManifestService(), ledger)
    artifact = tmp_path / "report.docx"
    artifact.write_bytes(b"artifact")

    with pytest.raises(ValueError, match="publication requires passed verification"):
        boundary.record_build(
            resolved=type("Resolved", (), {"doc_id": "report"})(),
            config={}, renderer=None, root=tmp_path, artifact=artifact,
            destination=tmp_path / "current.docx", output_format="docx",
            run_id="run-1", verification={"passed": False}, stage_artifacts=(),
        )

    assert ledger.calls == []


def test_stages_artifact_manifest_and_package_without_touching_publication_targets(tmp_path: Path) -> None:
    boundary = PipelinePublication(_ManifestService(), _Ledger())
    artifact = tmp_path / "report.docx"
    artifact.write_bytes(b"new artifact")
    manifest = _manifest()
    package = tmp_path / "release.zip"
    package.write_bytes(b"package")
    destination = tmp_path / "published.docx"
    destination.write_bytes(b"old artifact")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    boundary.stage(
        scratch=scratch, artifact=artifact, manifest=manifest,
        package_candidate=package, document_id="report", output_format="docx",
        existing=False,
    )

    assert destination.read_bytes() == b"old artifact"
    assert (scratch / "primary.docx").read_bytes() == b"new artifact"
    assert (scratch / "report.zip").read_bytes() == b"package"
    import json

    assert BuildManifest.from_dict(
        json.loads((scratch / "primary.docx.manifest.json").read_text())
    ) == manifest
