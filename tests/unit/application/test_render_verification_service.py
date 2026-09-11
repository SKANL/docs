from __future__ import annotations

from pathlib import Path

from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import ArtifactState, RenderProfile, VerificationFinding, VerificationReport


class RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RenderProfile, Path | None]] = []

    def verify(self, artifact, profile: RenderProfile, preview_dir: Path | None = None) -> VerificationReport:
        self.calls.append((artifact.path, profile, preview_dir))
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
    assert verifier.calls == [(artifact.as_posix(), RenderProfile(format="pdf", require_previews=True), previews)]


def test_verification_service_rejects_missing_artifact(tmp_path):
    try:
        RenderVerificationService(RecordingVerifier()).verify(tmp_path / "missing.pdf", RenderProfile(format="pdf"))
    except FileNotFoundError as error:
        assert "No existe artefacto" in str(error)
    else:
        raise AssertionError("expected missing artifact to fail")
