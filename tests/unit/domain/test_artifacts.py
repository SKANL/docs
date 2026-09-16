import json

import pytest

from docs.domain.artifacts import (
    ArtifactRef,
    ArtifactState,
    BuildManifest,
    VerificationFinding,
    VerificationReport,
)


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


def test_verification_report_serializes_preview_hashes():
    artifact = ArtifactRef("output/report.pdf", "a" * 64)
    report = VerificationReport(
        artifact=artifact,
        preview_hashes={"report-p01.png": "b" * 64},
    )

    assert report.to_dict()["artifact"]["sha256"] == "a" * 64
    assert report.to_dict()["preview_hashes"] == {"report-p01.png": "b" * 64}


def test_verification_report_serializes_optional_provenance_metadata():
    artifact = ArtifactRef("output/report.pdf", "a" * 64)
    report = VerificationReport(
        artifact=artifact,
        metadata={"config_hash": "c" * 64, "preview_dpi": 150},
    )

    assert report.to_dict()["metadata"] == {"config_hash": "c" * 64, "preview_dpi": 150}


@pytest.mark.parametrize("media_type", ["", 123, [], {}])
def test_artifact_ref_rejects_invalid_media_type_metadata(media_type):
    with pytest.raises(ValueError, match="media_type"):
        ArtifactRef("output/report.pdf", "b" * 64, media_type=media_type)


@pytest.mark.parametrize("size_bytes", [1.5, "12", True, [], {}])
def test_artifact_ref_rejects_non_integer_size_metadata(size_bytes):
    with pytest.raises(ValueError, match="size_bytes"):
        ArtifactRef("output/report.pdf", "b" * 64, size_bytes=size_bytes)


@pytest.mark.parametrize("sha256", [123, None, [], {}])
def test_artifact_ref_rejects_non_string_sha256_before_publication_validation(sha256):
    with pytest.raises(ValueError, match="sha256"):
        ArtifactRef("output/report.pdf", sha256)


def test_artifact_ref_preserves_current_records_without_metadata():
    artifact = ArtifactRef("output/report.pdf", "b" * 64)

    assert artifact.media_type is None
    assert artifact.size_bytes is None


def test_build_manifest_round_trips_rich_artifact_identity_fields():
    manifest = BuildManifest(
        document_id="report",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "1"},
        artifacts=(
            ArtifactRef(
                "output/report.pdf",
                "e" * 64,
                ArtifactState.VERIFIED,
                media_type="application/pdf",
                size_bytes=12,
            ),
        ),
        verification={"passed": True},
        provenance_run="run-1",
    )

    restored = BuildManifest.from_dict(manifest.to_dict())

    assert restored.artifacts[0] == manifest.artifacts[0]


def test_build_manifest_identity_distinguishes_relative_artifact_paths():
    """Breaks if identity reduces a relative artifact path to its filename."""
    common = {
        "document_id": "report",
        "source_hash": "a" * 64,
        "template_hash": "b" * 64,
        "config_hash": "c" * 64,
        "context_hash": "d" * 64,
        "renderer_versions": {"renderer": "1"},
        "verification": {"passed": True},
    }

    alpha = BuildManifest(
        **common,
        artifacts=(ArtifactRef("alpha/report.docx", "e" * 64, ArtifactState.READY),),
    )
    beta = BuildManifest(
        **common,
        artifacts=(ArtifactRef("beta/report.docx", "e" * 64, ArtifactState.READY),),
    )

    assert alpha.identity() != beta.identity()
