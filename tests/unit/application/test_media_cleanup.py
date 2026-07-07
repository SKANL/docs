# tests/unit/application/test_media_cleanup.py
"""Orphan `_media/` cleanup (Front B, design.md Decision 8 #13; spec:
document-ingest "Orphan Media Directory Cleanup"). Runs as a step during the
ingest scan over `sections/ingested/` -- content-addressed orphans (a
`<stem>-<kind>-<sha8>_media/` sibling whose paired `.md` output no longer
exists) are removed; anything not matching that shape is refused (left in
place) and reported, never silently skipped."""
from __future__ import annotations

from pathlib import Path

from docs.application.ingest import IngestService


class _FakeDetector:
    def detect(self, path: Path) -> str:
        return ""


def _service() -> IngestService:
    return IngestService(_FakeDetector(), {})


def test_content_addressed_orphan_media_dir_is_removed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    orphan_media = ingested_dir / "readme-md-a1b2c3d4_media"
    orphan_media.mkdir(parents=True)
    (orphan_media / "image1.png").write_bytes(b"fake-png-bytes")
    # No paired readme-md-a1b2c3d4.md exists -- this media dir is orphaned.

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert not orphan_media.exists()
    assert report["media_cleanup"]["removed"] == ["readme-md-a1b2c3d4_media"]


def test_content_addressed_media_dir_with_paired_md_is_preserved(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    referenced_media = ingested_dir / "readme-md-a1b2c3d4_media"
    referenced_media.mkdir(parents=True)
    (referenced_media / "image1.png").write_bytes(b"fake-png-bytes")
    (ingested_dir / "readme-md-a1b2c3d4.md").write_text("# Readme", encoding="utf-8")

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert referenced_media.exists()
    assert report["media_cleanup"]["removed"] == []
    assert report["media_cleanup"]["refused"] == []


def test_foreign_non_content_addressed_media_dir_is_refused_not_deleted(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    foreign_dir = ingested_dir / "manually_added_media"
    foreign_dir.mkdir(parents=True)
    (foreign_dir / "notes.txt").write_text("do not delete me", encoding="utf-8")

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert foreign_dir.exists()
    assert (foreign_dir / "notes.txt").exists()
    assert report["media_cleanup"]["removed"] == []
    assert report["media_cleanup"]["refused"] == ["manually_added_media"]


def test_missing_ingested_dir_reports_empty_media_cleanup_no_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert report["media_cleanup"] == {"removed": [], "refused": []}
