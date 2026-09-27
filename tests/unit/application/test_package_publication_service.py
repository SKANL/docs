from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from docs.application.package_publication_service import (
    PackagePublicationError,
    PackagePublicationService,
    PackageSourceFile,
)
from docs.application.package_service import PackageService
from docs.cli.commands import document_app
from docs.domain.artifacts import ArtifactRef, BuildManifest
from docs.domain.pipeline_policy import PipelineMode


def _service() -> PackagePublicationService:
    return PackagePublicationService(
        archive_writer=PackageService(
            lock=lambda _path: nullcontext(),
            directory_guard=lambda _path: nullcontext(),
            normalize_docx_zip_timestamps=lambda _path: None,
            assert_directory_identity=lambda _path, _expected, *, operation: None,
        ),
        lock=lambda _path: nullcontext(),
    )


def test_package_rejects_a_source_directory_outside_output_current(tmp_path: Path) -> None:
    with pytest.raises(PackagePublicationError, match="output/current"):
        _service().package(tmp_path / "release.zip", tmp_path / "unverified")


def test_publish_preflight_rejects_an_artifact_outside_output_current(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "artifact.pdf"
    source.parent.mkdir()
    source.write_bytes(b"artifact")

    with pytest.raises(PackagePublicationError, match="matching manifest"):
        _service().preflight_publish(source, tmp_path / "release.pdf", policy=PipelineMode.release)


def test_publish_validates_request_before_resolving_current_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "outside" / "artifact.pdf"
    source.parent.mkdir()
    source.write_bytes(b"artifact")
    publication = SimpleNamespace(
        preflight_publish=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PackagePublicationError("publish requires an artifact with its matching manifest")
        )
    )
    ctx = SimpleNamespace(obj={"deps": SimpleNamespace(package_publications=publication)})
    monkeypatch.setattr(
        document_app,
        "_resolve_publish_inputs",
        lambda *_args: pytest.fail("current inputs must not resolve for an invalid publish request"),
    )

    with pytest.raises(typer.BadParameter, match="matching manifest"):
        document_app.publish(ctx, source, tmp_path / "release.pdf", PipelineMode.release, False)


def _publish_context() -> SimpleNamespace:
    return SimpleNamespace(obj={"deps": SimpleNamespace(package_publications=_service())})


def _current_artifact(tmp_path: Path) -> Path:
    source = tmp_path / "output" / "current" / "artifact.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"artifact")
    return source


def _assert_current_inputs_are_not_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_app,
        "_resolve_publish_inputs",
        lambda *_args: pytest.fail("current inputs must not resolve for invalid publish evidence"),
    )


def test_publish_rejects_malformed_manifest_before_resolving_current_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _current_artifact(tmp_path)
    source.with_suffix(".pdf.manifest.json").write_text("not json", encoding="utf-8")
    _assert_current_inputs_are_not_resolved(monkeypatch)

    with pytest.raises(typer.BadParameter, match="valid manifest"):
        document_app.publish(_publish_context(), source, tmp_path / "release.pdf", PipelineMode.release, False)


def test_publish_rejects_manifest_hash_mismatch_before_resolving_current_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _current_artifact(tmp_path)
    manifest = BuildManifest(
        document_id="doc",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "1"},
        artifacts=(ArtifactRef(str(source.resolve()), "0" * 64),),
        verification={"passed": True},
        provenance_run="run",
    )
    source.with_suffix(".pdf.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    _assert_current_inputs_are_not_resolved(monkeypatch)

    with pytest.raises(typer.BadParameter, match="artifact hash"):
        document_app.publish(_publish_context(), source, tmp_path / "release.pdf", PipelineMode.release, False)


def test_publish_rejects_missing_attestation_before_resolving_current_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _current_artifact(tmp_path)
    manifest = BuildManifest(
        document_id="doc",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "1"},
        artifacts=(ArtifactRef(str(source.resolve()), hashlib.sha256(source.read_bytes()).hexdigest()),),
        verification={"passed": True},
        provenance_run="missing-run",
    )
    source.with_suffix(".pdf.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    _assert_current_inputs_are_not_resolved(monkeypatch)

    with pytest.raises(typer.BadParameter, match="verifiable provenance attestation"):
        document_app.publish(_publish_context(), source, tmp_path / "release.pdf", PipelineMode.release, False)


def test_package_rejects_a_source_member_change_before_archive_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[object] = []
    archive_writer = SimpleNamespace(write=lambda *_args, **_kwargs: writes.append("write"))
    service = PackagePublicationService(archive_writer=archive_writer, lock=lambda _path: nullcontext())
    source_dir = tmp_path / "output" / "current"
    source_dir.mkdir(parents=True)
    source = source_dir / "artifact.pdf"
    source.write_bytes(b"pdf")
    before = service._read_snapshot(source, tmp_path)

    def snapshots(*_args: object, **_kwargs: object) -> tuple[PackageSourceFile, ...]:
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(b"pdf")
        os.replace(replacement, source)
        return (PackageSourceFile("artifact.pdf", before),)

    monkeypatch.setattr(service, "_package_files", snapshots)

    with pytest.raises(PackagePublicationError, match="source changed"):
        service.package(tmp_path / "release.zip", source_dir)

    assert writes == []
    after = service._read_snapshot(source, tmp_path)
    assert before.content == after.content == b"pdf"
    assert (before.device, before.inode, before.mode) != (after.device, after.inode, after.mode)


def test_package_file_snapshot_detects_same_content_inode_replacement(tmp_path: Path) -> None:
    source = tmp_path / "artifact.pdf"
    source.write_bytes(b"unchanged")
    service = _service()
    before = service._read_snapshot(source, tmp_path)
    replacement = tmp_path / "replacement.pdf"
    replacement.write_bytes(b"unchanged")
    os.replace(replacement, source)
    after = service._read_snapshot(source, tmp_path)

    assert before.content == after.content == b"unchanged"
    assert (before.device, before.inode, before.mode) != (after.device, after.inode, after.mode)


def test_publish_rechecks_attestation_after_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _current_artifact(tmp_path)
    manifest = BuildManifest(
        document_id="doc",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "1"},
        artifacts=(ArtifactRef(str(source.resolve()), hashlib.sha256(source.read_bytes()).hexdigest()),),
        verification={"passed": True},
        provenance_run="run",
    )
    source.with_suffix(".pdf.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    verdicts = iter([True, False])

    class Ledger:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def verify_attestation(self, *_args: object) -> bool:
            return next(verdicts)

    monkeypatch.setattr("docs.application.package_publication_service.ProvenanceLedger", Ledger)
    service = _service()
    prepared = service.preflight_publish(source, tmp_path / "release.pdf", policy=PipelineMode.release)

    with pytest.raises(PackagePublicationError, match="verifiable provenance attestation"):
        service.publish(
            prepared,
            current_identities={
                "template_hash": manifest.template_hash,
                "template_ir_hash": manifest.template_ir_hash,
                "config_hash": manifest.config_hash,
                "context_hash": manifest.context_hash,
                "asset_hashes": manifest.asset_hashes,
                "renderer_versions": manifest.renderer_versions,
                "source_hash": manifest.source_hash,
            },
        )
