"""Application service for v2 build manifests and provenance recording."""

from __future__ import annotations

import mimetypes
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest


class ProvenanceLedgerPort(Protocol):
    """Minimal ledger behavior required to attest a rendered artifact."""

    def record_run(
        self, run_id: str, *, inputs: Iterable[Path], outputs: Iterable[Path]
    ) -> object: ...

    def record_attestation(self, run_id: str, manifest: dict[str, Any]) -> object: ...


InputIdentities = Callable[..., Mapping[str, Any]]
BuildInputs = Callable[[Path], tuple[Path, ...]]
ArtifactHash = Callable[[Path], str]
ManifestWriter = Callable[[Path, str], None]


class BuildManifestServiceV2:
    """Create, persist, and attest v2 manifests through injected boundaries."""

    def __init__(
        self,
        *,
        input_identities: InputIdentities,
        build_inputs: BuildInputs,
        artifact_hash: ArtifactHash,
        write_text: ManifestWriter,
    ) -> None:
        self._input_identities = input_identities
        self._build_inputs = build_inputs
        self._artifact_hash = artifact_hash
        self._write_text = write_text

    def create_manifest(
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
        verification: dict[str, Any] | None = None,
    ) -> BuildManifest:
        identities = self._input_identities(
            resolved=resolved,
            config=config,
            renderer=renderer,
            root=root,
            output_format=output_format,
        )
        return BuildManifest(
            document_id=resolved.doc_id,
            source_hash=str(identities["source_hash"]),
            template_hash=str(identities["template_hash"]),
            config_hash=str(identities["config_hash"]),
            context_hash=str(identities["context_hash"]),
            asset_hashes=dict(identities["asset_hashes"]),
            renderer_versions=dict(identities["renderer_versions"]),
            artifacts=(
                ArtifactRef(
                    str(destination.resolve()),
                    self._artifact_hash(artifact),
                    ArtifactState.READY,
                    media_type=mimetypes.guess_type(destination.name)[0]
                    or "application/octet-stream",
                    size_bytes=artifact.stat().st_size,
                ),
            ),
            verification=verification or {"passed": True, "format": output_format},
            provenance_run=run_id,
        )

    def record_provenance(
        self,
        ledger: ProvenanceLedgerPort,
        run_id: str,
        root: Path,
        artifact: Path,
        manifest: BuildManifest,
    ) -> None:
        ledger.record_run(run_id, inputs=self._build_inputs(root), outputs=(artifact,))
        ledger.record_attestation(run_id, manifest.attestation())

    def write_manifest(self, manifest: BuildManifest, destination: Path) -> None:
        self._write_text(destination, manifest.to_json() + "\n")
