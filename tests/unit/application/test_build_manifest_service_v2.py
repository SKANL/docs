from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from docs.application.build_manifest_service_v2 import BuildManifestServiceV2
from docs.domain.artifacts import ArtifactState
from docs.domain.identity import canonical_json


class _Ledger:
    def __init__(self) -> None:
        self.run: tuple[str, tuple[Path, ...], tuple[Path, ...]] | None = None
        self.attestation: tuple[str, dict[str, object]] | None = None

    def record_run(self, run_id: str, *, inputs: tuple[Path, ...], outputs: tuple[Path, ...]) -> None:
        self.run = (run_id, inputs, outputs)

    def record_attestation(self, run_id: str, attestation: dict[str, object]) -> None:
        self.attestation = (run_id, attestation)


def test_build_manifest_service_creates_writes_and_records_provenance(tmp_path: Path) -> None:
    artifact = tmp_path / "runs" / "v2-artifacts" / "build.active.docx"
    destination = tmp_path / "output" / "v2" / "active.docx"
    manifest_path = tmp_path / "scratch" / "primary.docx.manifest.json"
    source = tmp_path / "sections" / "overview.md"
    rendered = b"rendered artifact"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(rendered)
    source.parent.mkdir()
    source.write_text("# OVERVIEW", encoding="utf-8")
    writes: list[tuple[Path, str]] = []
    ledger = _Ledger()
    identities = {
        "source_hash": "a" * 64,
        "template_hash": "b" * 64,
        "config_hash": "c" * 64,
        "context_hash": "d" * 64,
        "asset_hashes": {"assets/logo.png": "e" * 64},
        "renderer_versions": {"renderer": "f" * 64},
    }
    service = BuildManifestServiceV2(
        input_identities=lambda **_kwargs: identities,
        build_inputs=lambda _root: (source,),
        artifact_hash=lambda _path: "1" * 64,
        write_text=lambda path, content: writes.append((path, content)),
    )

    manifest = service.create_manifest(
        resolved=SimpleNamespace(doc_id="active"),
        config={"output": {"format": "docx"}},
        renderer=object(),
        root=tmp_path,
        artifact=artifact,
        destination=destination,
        output_format="docx",
        run_id="cli-build-docx",
        verification={"passed": True, "format": "docx"},
    )
    service.record_provenance(ledger, "cli-build-docx", tmp_path, artifact, manifest)
    service.write_manifest(manifest, manifest_path)

    assert manifest.artifacts[0].state is ArtifactState.READY
    assert manifest.artifacts[0].path == str(destination.resolve())
    assert ledger.run == ("cli-build-docx", (source,), (artifact,))
    assert ledger.attestation == ("cli-build-docx", manifest.attestation())
    assert writes == [(manifest_path, manifest.to_json() + "\n")]


def test_build_manifest_identity_and_attestation_ignore_run_id(tmp_path: Path) -> None:
    artifact = tmp_path / "runs" / "v2-artifacts" / "build.active.docx"
    destination = tmp_path / "output" / "v2" / "active.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"rendered artifact")
    identities = {
        "source_hash": "a" * 64,
        "template_hash": "b" * 64,
        "config_hash": "c" * 64,
        "context_hash": "d" * 64,
        "asset_hashes": {"assets/logo.png": "e" * 64},
        "renderer_versions": {"renderer": "f" * 64},
    }
    service = BuildManifestServiceV2(
        input_identities=lambda **_kwargs: identities,
        build_inputs=lambda _root: (),
        artifact_hash=lambda _path: "1" * 64,
        write_text=lambda _path, _content: None,
    )
    kwargs = {
        "resolved": SimpleNamespace(doc_id="active"),
        "config": {"output": {"format": "docx"}},
        "renderer": object(),
        "root": tmp_path,
        "artifact": artifact,
        "destination": destination,
        "output_format": "docx",
        "verification": {"passed": True, "format": "docx"},
    }

    first = service.create_manifest(**kwargs, run_id="first-run")
    second = service.create_manifest(**kwargs, run_id="second-run")

    assert first.provenance_run == "first-run"
    assert second.provenance_run == "second-run"
    assert first.identity() == second.identity()
    assert canonical_json(first.attestation()) == canonical_json(second.attestation())
