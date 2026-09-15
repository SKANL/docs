"""Reusable v2 packaging of verified build outputs."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_file

PackageWriter = Callable[[Path, Path], None]


class PackageReleaseServiceV2:
    """Assemble only verified build generations into a release candidate."""

    def __init__(
        self,
        *,
        artifact: Callable[[], Path | None],
        manifest: Callable[[], BuildManifest | None],
        document_id: str,
        output_format: str,
        source_dir: Path,
        destination: Path,
        ledger: ProvenanceLedgerV2,
        write_package: PackageWriter,
        candidate_sink: Callable[[Path], None] | None = None,
        verify_current_build: bool = True,
    ) -> None:
        self._artifact = artifact
        self._manifest = manifest
        self._document_id = document_id
        self._output_format = output_format
        self._source_dir = source_dir
        self._destination = destination
        self._ledger = ledger
        self._write_package = write_package
        self._candidate_sink = candidate_sink
        self._verify_current_build = verify_current_build

    def release(self) -> tuple[bool, str]:
        artifact = self._artifact()
        manifest = self._manifest()
        if artifact is None or manifest is None:
            return False, "package-release requires a verified artifact and manifest"
        try:
            manifest.validate_for_publication()
        except ValueError as exc:
            return False, str(exc)
        if self._verify_current_build and (
            manifest.document_id != self._document_id
            or not manifest.artifacts
            or sha256_file(artifact) != manifest.artifacts[0].sha256
            or not self._ledger.verify_attestation(
                manifest.provenance_run, manifest.attestation()
            )
        ):
            return False, "package-release manifest is not attested for the current build"

        self._source_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".v2-package-", dir=self._source_dir.parent))
        candidate = self._destination.with_name(f".{self._destination.name}.candidate")
        try:
            self._copy_verified_existing_outputs(staging)
            package_name = f"{self._document_id}.{self._output_format}"
            shutil.copyfile(artifact, staging / package_name)
            (staging / f"{package_name}.manifest.json").write_text(
                manifest.to_json() + "\n", encoding="utf-8"
            )
            self._write_package(candidate, staging)
        except (OSError, TypeError, ValueError, KeyError, IndexError) as exc:
            return False, str(exc)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if self._candidate_sink is not None:
            self._candidate_sink(candidate)
        return True, str(candidate)

    def _copy_verified_existing_outputs(self, staging: Path) -> None:
        if not self._source_dir.is_dir():
            return
        for existing in sorted(self._source_dir.iterdir(), key=lambda path: path.name):
            if existing.is_symlink() or not existing.is_file():
                raise ValueError(f"package refuses unsafe source entry: {existing.name}")
            if existing.name.endswith(".manifest.json"):
                continue
            manifest_path = existing.with_name(existing.name + ".manifest.json")
            if not manifest_path.is_file() or manifest_path.is_symlink():
                continue
            try:
                previous = BuildManifest.from_dict(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
                previous.validate_for_publication()
                if (
                    previous.document_id != self._document_id
                    or not self._ledger.verify_attestation(
                        previous.provenance_run, previous.attestation()
                    )
                    or sha256_file(existing) != previous.artifacts[0].sha256
                ):
                    continue
            except (OSError, TypeError, ValueError, KeyError, IndexError):
                continue
            shutil.copyfile(existing, staging / existing.name)
            shutil.copyfile(manifest_path, staging / manifest_path.name)
