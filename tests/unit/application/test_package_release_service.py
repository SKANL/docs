from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from docs.application.package_release_service import PackageReleaseService


def test_package_release_service_packages_current_verified_generation_atomically(tmp_path: Path) -> None:
    artifact = tmp_path / "document.docx"
    artifact.write_bytes(b"verified build")
    destination = tmp_path / "output" / "release" / "document.zip"
    writes: list[tuple[Path, Path]] = []
    staged_files: dict[str, bytes] = {}

    manifest = SimpleNamespace(
        document_id="document",
        provenance_run="run-1",
        artifacts=(SimpleNamespace(sha256=hashlib.sha256(b"verified build").hexdigest()),),
        validate_for_publication=lambda: None,
        to_json=lambda: '{"provenance_run":"run-1"}',
        attestation=lambda: {"manifest": "current"},
    )

    service = PackageReleaseService(
        artifact=lambda: artifact,
        manifest=lambda: manifest,
        document_id="document",
        output_format="docx",
        source_dir=tmp_path / "output" / "v2",
        destination=destination,
        ledger=SimpleNamespace(verify_attestation=lambda run, attestation: True),
        write_package=lambda candidate, staging: (
            writes.append((candidate, staging)),
            staged_files.update(
                {path.name: path.read_bytes() for path in staging.iterdir()}
            ),
        ),
    )

    result = service.release()

    assert result == (True, str(destination.with_name(".document.zip.candidate")))
    assert writes and writes[0][0] == destination.with_name(".document.zip.candidate")
    assert staged_files["document.docx"] == b"verified build"
    assert staged_files["document.docx.manifest.json"].decode().splitlines() == [
        '{"provenance_run":"run-1"}'
    ]


def test_package_release_service_rejects_a_manifest_not_attested_for_the_current_build(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "document.docx"
    artifact.write_bytes(b"verified build")
    manifest = SimpleNamespace(
        document_id="document",
        provenance_run="old-run",
        artifacts=(SimpleNamespace(sha256="wrong"),),
        validate_for_publication=lambda: None,
        attestation=lambda: {"manifest": "old"},
    )
    service = PackageReleaseService(
        artifact=lambda: artifact,
        manifest=lambda: manifest,
        document_id="document",
        output_format="docx",
        source_dir=tmp_path / "output" / "v2",
        destination=tmp_path / "release.zip",
        ledger=SimpleNamespace(verify_attestation=lambda run, attestation: False),
        write_package=lambda candidate, staging: None,
    )

    assert service.release() == (False, "package-release manifest is not attested for the current build")
