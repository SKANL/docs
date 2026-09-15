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


def test_build_manifest_rejects_artifact_records_with_invalid_hashes():
    manifest = BuildManifest(
        document_id="example",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"docx": "test"},
        artifacts=(ArtifactRef("output.docx", "not-a-digest", ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-001",
    )

    with pytest.raises(ValueError, match=r"artifact.*SHA-256"):
        manifest.validate_for_publication()


def test_build_manifest_rejects_non_string_artifact_paths_during_publication():
    manifest = BuildManifest(
        document_id="example",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"docx": "test"},
        artifacts=(ArtifactRef(123, "e" * 64, ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-001",
    )

    with pytest.raises(ValueError, match=r"artifact path.*string"):
        manifest.validate_for_publication()


@pytest.mark.parametrize("provenance_run", [None, "", 123, [], {}])
def test_build_manifest_rejects_non_string_or_empty_provenance_run(provenance_run):
    manifest = BuildManifest(
        document_id="example",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"docx": "test"},
        artifacts=(ArtifactRef("output.docx", "e" * 64, ArtifactState.READY),),
        verification={"passed": True},
        provenance_run=provenance_run,
    )

    with pytest.raises(ValueError, match="provenance run"):
        manifest.validate_for_publication()


def test_build_manifest_rejects_malformed_hash_maps_without_attribute_errors():
    with pytest.raises(ValueError, match="asset_hashes must be a mapping"):
        BuildManifest.from_dict(
            {"schema": "docs.build/v2", "document_id": "example", "asset_hashes": []}
        )


@pytest.mark.parametrize("asset_hash", [123, 1.5, None, [], {}])
def test_build_manifest_rejects_non_string_asset_hashes_without_coercion(asset_hash):
    with pytest.raises(ValueError, match="asset_hashes"):
        BuildManifest.from_dict(
            {
                "schema": "docs.build/v2",
                "document_id": "example",
                "asset_hashes": {"hero.png": asset_hash},
            }
        )


def test_build_manifest_preserves_valid_current_asset_hashes():
    manifest = BuildManifest.from_dict(
        {
            "schema": "docs.build/v2",
            "document_id": "example",
            "asset_hashes": {"hero.png": "current-digest"},
        }
    )

    assert manifest.asset_hashes == {"hero.png": "current-digest"}


@pytest.mark.parametrize("renderer_version", [123, 1.5, None, [], {}])
def test_build_manifest_rejects_non_string_renderer_versions_without_coercion(renderer_version):
    with pytest.raises(ValueError, match="renderer_versions"):
        BuildManifest.from_dict(
            {
                "schema": "docs.build/v2",
                "document_id": "example",
                "renderer_versions": {"docx": renderer_version},
            }
        )


@pytest.mark.parametrize("renderer_versions", [None, [], "renderer"])
def test_build_manifest_constructor_rejects_non_mapping_renderer_versions(renderer_versions):
    with pytest.raises(ValueError, match="renderer_versions"):
        BuildManifest(document_id="example", renderer_versions=renderer_versions)


@pytest.mark.parametrize("renderer_versions", [{123: "version"}, {"docx": 123}])
def test_build_manifest_constructor_rejects_non_string_renderer_version_keys_and_values(renderer_versions):
    with pytest.raises(ValueError, match="renderer_versions"):
        BuildManifest(document_id="example", renderer_versions=renderer_versions)


def test_build_manifest_rejects_renderer_version_mutations_during_serialization_and_publication():
    renderer_versions = {"docx": "test"}
    manifest = BuildManifest(document_id="example", renderer_versions=renderer_versions)
    renderer_versions["docx"] = 123

    with pytest.raises(ValueError, match="renderer_versions"):
        manifest.to_json()
    with pytest.raises(ValueError, match="renderer_versions"):
        manifest.validate_for_publication()


@pytest.mark.parametrize(
    "field",
    ["document_id", "source_hash", "template_hash", "config_hash", "context_hash"],
)
@pytest.mark.parametrize("value", [None, 123, [], {}])
def test_build_manifest_rejects_non_string_top_level_identity_fields(field, value):
    with pytest.raises(ValueError, match=field):
        BuildManifest.from_dict({"schema": "docs.build/v2", field: value})


@pytest.mark.parametrize("entry", [None, [], {"path": "output.docx"}])
def test_build_manifest_normalizes_malformed_artifact_entries(entry):
    with pytest.raises(ValueError, match="artifact entry"):
        BuildManifest.from_dict(
            {"schema": "docs.build/v2", "artifacts": [entry]}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("path", 123), ("path", None), ("sha256", 456), ("sha256", None), ("state", 789), ("state", None)],
)
def test_build_manifest_rejects_non_string_artifact_identity_fields(field, value):
    entry = {"path": "output.docx", "sha256": "current-digest", "state": "ready"}
    entry[field] = value

    with pytest.raises(ValueError, match=field):
        BuildManifest.from_dict(
            {"schema": "docs.build/v2", "artifacts": [entry]}
        )


def test_build_manifest_rejects_unknown_artifact_state_with_actionable_error():
    with pytest.raises(ValueError, match=r"state.*planned, generated"):
        BuildManifest.from_dict(
            {
                "schema": "docs.build/v2",
                "artifacts": [
                    {"path": "output.docx", "sha256": "current-digest", "state": "complete"}
                ],
            }
        )


def test_build_manifest_constructor_normalizes_malformed_artifact_entries():
    with pytest.raises(ValueError, match="artifact entry"):
        BuildManifest(document_id="example", artifacts=[None])
