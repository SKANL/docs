from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.domain.artifacts import ArtifactRef, ArtifactState, RenderProfile, VerificationFinding, VerificationReport
from docs.domain.ports.render_verification_port import RenderVerificationPort


class RenderVerificationService:
    """Prepare immutable artifact identity, then delegate format-specific inspection."""

    def __init__(self, port: RenderVerificationPort) -> None:
        self.port = port

    def verify(
        self,
        artifact_path: Path,
        profile: RenderProfile,
        preview_dir: Path | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        artifact_path = Path(artifact_path)
        if not artifact_path.is_file():
            raise FileNotFoundError(f"No existe artefacto para verificar: {artifact_path}")
        digest = self._sha256(artifact_path)
        artifact = ArtifactRef(
            path=artifact_path.resolve().as_posix(),
            sha256=digest,
            state=ArtifactState.READY,
            media_type=mimetypes.guess_type(artifact_path.name)[0]
            or "application/octet-stream",
            size_bytes=artifact_path.stat().st_size,
        )
        if config is None:
            report = self.port.verify(artifact, profile, preview_dir)
        else:
            report = self.port.verify(artifact, profile, preview_dir, config)
        if self._sha256(artifact_path) != digest:
            return VerificationReport(
                artifact=artifact,
                findings=[
                    *report.findings,
                    VerificationFinding(
                        "artifact.identity_changed",
                        "El artefacto cambió durante la inspección; el reporte no es confiable.",
                    ),
                ],
            )
        return report

    @staticmethod
    def _sha256(path: Path) -> str:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
