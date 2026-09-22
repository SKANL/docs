"""Read-only reporting for derived document artifacts."""

from __future__ import annotations

import mimetypes
from difflib import unified_diff
from pathlib import Path

from docs.domain.identity import sha256_file


class ArtifactReportService:
    """Inspect and compare artifacts without mutating the workspace."""

    def inspect(self, artifact: Path) -> dict[str, object]:
        return {
            "path": str(artifact.resolve()),
            "media_type": mimetypes.guess_type(artifact.name)[0] or "application/octet-stream",
            "sha256": sha256_file(artifact),
            "size_bytes": artifact.stat().st_size,
        }

    def compare(self, left: Path, right: Path) -> dict[str, object]:
        left_report = self.inspect(left)
        right_report = self.inspect(right)
        try:
            left_text = left.read_text(encoding="utf-8").splitlines(keepends=True)
            right_text = right.read_text(encoding="utf-8").splitlines(keepends=True)
            text_diff = list(
                unified_diff(left_text, right_text, fromfile=str(left), tofile=str(right))
            )
        except UnicodeDecodeError:
            text_diff = []
        return {
            "same": left_report["sha256"] == right_report["sha256"],
            "left": left_report,
            "right": right_report,
            "text_diff": text_diff,
        }
