"""Application boundary for attested pipeline publication."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from docs.application.build_manifest_service import BuildManifestService
from docs.application.provenance import ProvenanceLedger
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_file


class PipelinePublication:
    """Create provenance and stage verified outputs for atomic publication."""

    def __init__(self, manifests: BuildManifestService, ledger: ProvenanceLedger) -> None:
        self._manifests = manifests
        self._ledger = ledger

    def record_existing(
        self, document_id: str, artifact: Any, manifest: Any
    ) -> tuple[bool, str, str | None]:
        """Validate a persisted attestation before allowing a publish operation."""
        if not isinstance(manifest, BuildManifest):
            return False, "publish requires an attested artifact/manifest pair", None
        try:
            manifest.validate_for_publication()
        except ValueError as exc:
            return False, str(exc), None
        digest = sha256_file(artifact) if isinstance(artifact, Path) else ""
        if (
            not isinstance(artifact, Path)
            or manifest.document_id != document_id
            or not any(item.sha256 == digest for item in manifest.artifacts)
            or not self._ledger.verify_attestation(
                manifest.provenance_run or "", manifest.attestation()
            )
        ):
            return False, "publish requires an attested artifact/manifest pair", None
        return True, "reused verified artifact and manifest", digest

    def record_build(
        self,
        *,
        resolved: Any,
        config: dict[str, Any],
        renderer: Any,
        root: Path,
        artifact: Path,
        destination: Path,
        output_format: str,
        run_id: str,
        verification: dict[str, Any] | None,
        stage_artifacts: tuple[Any, ...],
    ) -> BuildManifest:
        """Create and attest a manifest only after the verification stage passed."""
        manifest = self._manifests.create_manifest(
            resolved=resolved,
            config=config,
            renderer=renderer,
            root=root,
            artifact=artifact,
            destination=destination,
            output_format=output_format,
            run_id=run_id,
            verification=verification,
            stage_artifacts=stage_artifacts,
        )
        manifest.validate_for_publication()
        self._manifests.record_provenance(
            self._ledger, run_id, root, artifact, manifest
        )
        return manifest

    def stage(
        self,
        *,
        scratch: Path,
        artifact: Any,
        manifest: Any,
        package_candidate: Any,
        document_id: str,
        output_format: str,
        existing: bool,
        persisted_manifest: Any = None,
        expected_digest: Any = None,
    ) -> None:
        """Materialize staged publication inputs; the transaction owns final commit."""
        staged = scratch / f"primary.{output_format}"
        staged_manifest = scratch / f"primary.{output_format}.manifest.json"
        staged_package = scratch / f"{document_id}.zip"
        staged.parent.mkdir(parents=True, exist_ok=True)
        if existing:
            if (
                not isinstance(artifact, Path)
                or not isinstance(manifest, BuildManifest)
                or not isinstance(persisted_manifest, Path)
                or not isinstance(expected_digest, str)
                or persisted_manifest.is_symlink()
            ):
                raise RuntimeError("publish requires an attested artifact/manifest pair")
            shutil.copyfile(artifact, staged)
            shutil.copyfile(persisted_manifest, staged_manifest)
            try:
                staged_data = BuildManifest.from_dict(
                    json.loads(staged_manifest.read_text(encoding="utf-8"))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError("persisted manifest changed before publication") from exc
            if staged_data != manifest:
                raise RuntimeError("persisted manifest changed before publication")
        else:
            if not isinstance(artifact, Path) or not isinstance(manifest, BuildManifest):
                raise RuntimeError("publish requires a verified artifact and manifest")
            shutil.copyfile(artifact, staged)
            self._manifests.write_manifest(manifest, staged_manifest)
        if not isinstance(package_candidate, Path) or not package_candidate.is_file():
            raise RuntimeError("package-release completed without a safe release candidate")
        shutil.copyfile(package_candidate, staged_package)
        if existing and sha256_file(staged) != expected_digest:
            raise RuntimeError("artifact changed before publication")
