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


def test_artifact_verification_can_record_media_size_page_and_evidence():
    artifact = ArtifactRef(
        path="output/report.pdf",
        sha256="b" * 64,
        media_type="application/pdf",
        size_bytes=2048,
    )
    finding = VerificationFinding(
        code="layout.overflow",
        message="Content exceeds page bounds",
        severity="error",
        path="output/report.pdf",
        page=3,
        evidence={"right": 612, "page_width": 612},
    )
    report = VerificationReport(artifact=artifact, findings=[finding])

    payload = report.to_dict()

    assert payload["artifact"]["media_type"] == "application/pdf"
    assert payload["artifact"]["size_bytes"] == 2048
    assert payload["findings"][0]["page"] == 3
