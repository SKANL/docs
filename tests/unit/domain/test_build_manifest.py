from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest


def test_build_manifest_serializes_sources_and_outputs_deterministically():
    manifest = BuildManifest(
        document_id="example",
        source_hash="source",
        template_hash="template",
        config_hash="config",
        context_hash="context",
        asset_hashes={"hero.png": "asset"},
        renderer_versions={"docx": "python-docx"},
        artifacts=(ArtifactRef("output.docx", "output", ArtifactState.PUBLISHED),),
        verification={"passed": True, "blocking_findings": []},
        provenance_run="run-1",
    )

    assert manifest.to_dict()["schema"] == "docs.build/v2"
    assert manifest.to_json() == BuildManifest(**manifest.to_dict_without_schema()).to_json()


def test_build_manifest_keeps_artifacts_sorted_and_round_trippable():
    manifest = BuildManifest(
        document_id="example",
        asset_hashes={"z": "2", "a": "1"},
        renderer_versions={"pdf": "2", "docx": "1"},
        artifacts=(
            ArtifactRef("z.pdf", "z", ArtifactState.PUBLISHED),
            ArtifactRef("a.docx", "a", ArtifactState.READY),
        ),
    )

    payload = manifest.to_dict()
    assert list(payload["asset_hashes"]) == ["a", "z"]
    assert list(payload["renderer_versions"]) == ["docx", "pdf"]
    assert [item["path"] for item in payload["artifacts"]] == ["a.docx", "z.pdf"]
    assert BuildManifest.from_dict(payload).to_json() == manifest.to_json()


import pytest


def test_build_manifest_rejects_incomplete_or_unverified_release_payloads():
    with pytest.raises(ValueError, match="document_id"):
        BuildManifest(document_id="").validate_for_publication()
    with pytest.raises(ValueError, match="source_hash"):
        BuildManifest(document_id="example").validate_for_publication()
    with pytest.raises(ValueError, match="passed verification"):
        BuildManifest(
            document_id="example",
            source_hash="a" * 64,
            template_hash="b" * 64,
            config_hash="c" * 64,
            context_hash="d" * 64,
            artifacts=(ArtifactRef("out.docx", "e" * 64, ArtifactState.READY),),
            verification={"passed": False},
        ).validate_for_publication()


def test_build_manifest_attestation_is_deterministic_and_requires_a_verifiable_run():
    manifest = BuildManifest(
        document_id="example",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        asset_hashes={"assets/hero.png": "e" * 64},
        renderer_versions={"renderer": "f" * 64},
        artifacts=(ArtifactRef("output.docx", "1" * 64, ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-001",
    )

    attestation = manifest.attestation()

    assert attestation == BuildManifest.from_dict(manifest.to_dict()).attestation()
    assert attestation["sha256"] == manifest.attestation()["sha256"]
    assert "timestamp" not in manifest.to_json()
    assert "timestamp" not in str(attestation)
    manifest.validate_for_publication()
