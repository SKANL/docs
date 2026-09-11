import json

from docs.domain.artifacts import ArtifactRef, ArtifactState, VerificationFinding, VerificationReport


def test_artifact_models_serialize_to_a_stable_json_payload():
    """Breaks if artifact payload ordering or enum values drift."""
    artifact = ArtifactRef(path="output/report.pdf", sha256="a" * 64, state=ArtifactState.PUBLISHED)
    report = VerificationReport(
        artifact=artifact,
        findings=[VerificationFinding(code="pdf.page_count", message="Expected 2 pages", severity="error")],
    )

    assert json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) == (
        '{"artifact":{"path":"output/report.pdf","sha256":"'
        + "a" * 64
        + '","state":"published"},"findings":[{"code":"pdf.page_count","message":"Expected 2 pages","severity":"error"}],"passed":false}'
    )


def test_verification_report_passes_when_it_has_no_error_findings():
    artifact = ArtifactRef(path="output/report.pdf", sha256="a" * 64, state=ArtifactState.PUBLISHED)

    report = VerificationReport(
        artifact=artifact,
        findings=[VerificationFinding(code="pdf.font", message="Fallback font", severity="warning")],
    )

    assert report.passed is True
