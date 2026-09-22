from __future__ import annotations

from pathlib import Path

from docs.application.artifact_report_service import ArtifactReportService


def test_artifact_report_service_reports_identity_and_text_diff(tmp_path: Path) -> None:
    left = tmp_path / "before.txt"
    right = tmp_path / "after.txt"
    left.write_text("first\nsecond\n", encoding="utf-8")
    right.write_text("first\nchanged\n", encoding="utf-8")

    result = ArtifactReportService().compare(left, right)

    assert result["same"] is False
    assert result["left"] == ArtifactReportService().inspect(left)
    assert result["right"] == ArtifactReportService().inspect(right)
    assert result["text_diff"] == [
        f"--- {left}\n",
        f"+++ {right}\n",
        "@@ -1,2 +1,2 @@\n",
        " first\n",
        "-second\n",
        "+changed\n",
    ]


def test_artifact_report_service_omits_text_diff_for_binary_artifacts(tmp_path: Path) -> None:
    left = tmp_path / "before.bin"
    right = tmp_path / "after.bin"
    left.write_bytes(b"\xff")
    right.write_bytes(b"\xfe")

    result = ArtifactReportService().compare(left, right)

    assert result["same"] is False
    assert result["text_diff"] == []
