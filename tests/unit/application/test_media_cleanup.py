# tests/unit/application/test_media_cleanup.py
"""Orphan `_media/` cleanup (Front B, design.md Decision 8 #13; spec:
document-ingest "Orphan Media Directory Cleanup"). Runs as a step during the
ingest scan over `sections/ingested/` -- content-addressed orphans (a
`<stem>-<kind>-<sha8>_media/` sibling whose paired `.md` output no longer
exists) are removed; anything not matching that shape, OR whose contents
don't look like pandoc-extracted media, is refused (left in place, whole
directory, never partial-delete) and reported with a cause, never silently
skipped.

Hardened (fresh-context verify, PR2 fix batch, WARNING-1 + SUGGESTION-1): a
shape-matching orphan directory containing a foreign (non-media) file used to
be destroyed wholesale along with the human file inside it -- fails toward
refusal now instead. A per-item filesystem error (e.g. a symlink `rmtree`
refuses to follow) is caught and reported as a refused item with a cause,
never aborting the rest of the scan."""
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
    refused = report["media_cleanup"]["refused"]
    assert [r["path"] for r in refused] == ["manually_added_media"]
    assert "shape" in refused[0]["cause"]


def test_missing_ingested_dir_reports_empty_media_cleanup_no_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert report["media_cleanup"] == {"removed": [], "refused": []}


def test_foreign_file_inside_shape_matching_orphan_dir_survives_whole_dir_refused(tmp_path: Path):
    # WARNING-1 (fresh-context verify, PR2 fix batch) -- verifier's exact
    # reproduction: a directory named exactly like a real content-addressed
    # orphan, containing BOTH a plausible pandoc-extracted image AND a
    # clearly human-authored file. The old behavior destroyed the whole
    # directory (including the human file) via an unconditional rmtree.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    orphan_media = ingested_dir / "readme-md-a1b2c3d4_media"
    orphan_media.mkdir(parents=True)
    (orphan_media / "image1.png").write_bytes(b"fake-png-bytes")
    (orphan_media / "my_personal_notes.txt").write_text("do not delete me", encoding="utf-8")
    # No paired readme-md-a1b2c3d4.md -- this dir would otherwise be an orphan.

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert orphan_media.exists()
    assert (orphan_media / "image1.png").exists()
    assert (orphan_media / "my_personal_notes.txt").exists()
    assert report["media_cleanup"]["removed"] == []
    refused = report["media_cleanup"]["refused"]
    assert [r["path"] for r in refused] == ["readme-md-a1b2c3d4_media"]
    assert "my_personal_notes.txt" in refused[0]["cause"]


def test_orphan_dir_with_only_recognized_media_extensions_is_still_removed(tmp_path: Path):
    # Regression guard: the new content inspection must not become
    # over-eager and refuse genuinely clean pandoc-shaped media.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    orphan_media = ingested_dir / "readme-md-a1b2c3d4_media"
    orphan_media.mkdir(parents=True)
    (orphan_media / "image1.png").write_bytes(b"fake-png-bytes")
    nested = orphan_media / "media"
    nested.mkdir()
    (nested / "image2.jpeg").write_bytes(b"fake-jpeg-bytes")

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert not orphan_media.exists()
    assert report["media_cleanup"]["removed"] == ["readme-md-a1b2c3d4_media"]
    assert report["media_cleanup"]["refused"] == []


def test_orphan_dir_removal_error_is_reported_and_does_not_abort_scan(tmp_path: Path, monkeypatch):
    # SUGGESTION-1 (fresh-context verify, PR2 fix batch) -- an OSError on one
    # directory (e.g. a symlink shutil.rmtree refuses to follow) must be
    # caught per-item and reported as refused with a cause, never abort the
    # whole ingest_inbox call. Mirrors _ingest_one_safely's existing
    # per-file try/except convention already in this same module.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    ingested_dir = tmp_path / "sections" / "ingested"
    failing_media = ingested_dir / "readme-md-a1b2c3d4_media"
    failing_media.mkdir(parents=True)
    (failing_media / "image1.png").write_bytes(b"fake-png-bytes")
    ok_media = ingested_dir / "other-md-deadbeef_media"
    ok_media.mkdir(parents=True)
    (ok_media / "image2.png").write_bytes(b"fake-png-bytes")

    import shutil

    real_rmtree = shutil.rmtree

    def _raising_rmtree(path, *args, **kwargs):
        if Path(path).name == "readme-md-a1b2c3d4_media":
            raise OSError("Cannot call rmtree on a symbolic link")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("docs.application.ingest.shutil.rmtree", _raising_rmtree)

    report = _service().ingest_inbox(inbox, tmp_path / "sections")

    assert failing_media.exists()  # the raising item survives, untouched
    assert not ok_media.exists()  # the OTHER item still gets cleaned up
    assert report["media_cleanup"]["removed"] == ["other-md-deadbeef_media"]
    refused = report["media_cleanup"]["refused"]
    assert [r["path"] for r in refused] == ["readme-md-a1b2c3d4_media"]
    assert "symbolic link" in refused[0]["cause"]
