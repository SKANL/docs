from __future__ import annotations

import hashlib
from pathlib import Path

from docs.domain.artifacts import ArtifactRef, ArtifactState, RenderProfile, VerificationReport
from docs.domain.ports.render_verification_port import RenderVerificationPort


class RenderVerificationService:
    """Prepare immutable artifact identity, then delegate format-specific inspection."""

    def __init__(self, port: RenderVerificationPort) -> None:
        self.port = port

    def verify(
        self, artifact_path: Path, profile: RenderProfile, preview_dir: Path | None = None
    ) -> VerificationReport:
        artifact_path = Path(artifact_path)
        if not artifact_path.is_file():
            raise FileNotFoundError(f"No existe artefacto para verificar: {artifact_path}")
        with artifact_path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        artifact = ArtifactRef(
            path=artifact_path.resolve().as_posix(),
            sha256=digest,
            state=ArtifactState.READY,
        )
        return self.port.verify(artifact, profile, preview_dir)
