from __future__ import annotations

from pathlib import Path

from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import ArtifactState, RenderProfile, VerificationFinding, VerificationReport


class RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RenderProfile, Path | None, object]] = []

    def verify(self, artifact, profile: RenderProfile, preview_dir: Path | None = None, config=None) -> VerificationReport:
        self.calls.append((artifact.path, profile, preview_dir, config))
        return VerificationReport(
            artifact=artifact,
            findings=[VerificationFinding(code="render.page.1", message="page 1 is valid", severity="info")],
        )


def test_verification_service_hashes_artifact_and_delegates_profile(tmp_path):
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"pdf-bytes")
    previews = tmp_path / "previews"
    verifier = RecordingVerifier()

    report = RenderVerificationService(verifier).verify(
        artifact, RenderProfile(format="pdf", require_previews=True), preview_dir=previews
    )

    assert report.passed is True
    assert report.artifact.path == artifact.as_posix()
    assert report.artifact.state is ArtifactState.READY
    assert len(report.artifact.sha256) == 64
    assert verifier.calls == [(artifact.as_posix(), RenderProfile(format="pdf", require_previews=True), previews, None)]


def test_verification_service_forwards_renderer_config(tmp_path):
    artifact = tmp_path / "report.docx"
    artifact.write_bytes(b"docx-bytes")
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}
    verifier = RecordingVerifier()

    RenderVerificationService(verifier).verify(artifact, RenderProfile(format="docx"), config=config)

    assert verifier.calls[0][3] is config


def test_verification_service_rejects_missing_artifact(tmp_path):
    try:
        RenderVerificationService(RecordingVerifier()).verify(tmp_path / "missing.pdf", RenderProfile(format="pdf"))
    except FileNotFoundError as error:
        assert "No existe artefacto" in str(error)
    else:
        raise AssertionError("expected missing artifact to fail")


def test_verification_service_fails_when_artifact_changes_during_inspection(tmp_path):
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"before")

    class MutatingVerifier(RecordingVerifier):
        def verify(self, checked_artifact, profile: RenderProfile, preview_dir: Path | None = None, config=None) -> VerificationReport:
            artifact.write_bytes(b"after")
            return VerificationReport(artifact=checked_artifact)

    report = RenderVerificationService(MutatingVerifier()).verify(artifact, RenderProfile(format="pdf"))

    assert report.passed is False
    assert any(finding.code == "artifact.identity_changed" and finding.severity == "error" for finding in report.findings)
