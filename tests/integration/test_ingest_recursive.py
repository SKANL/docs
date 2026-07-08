# tests/integration/test_ingest_recursive.py
"""Recursive inbox walk (Front C, design.md Decision 2; spec: document-ingest
"Recursive Inbox Scan with Provenance"). `inbox_dir.iterdir()` (one level)
becomes an `rglob`-based recursive walk, manually sorted by POSIX relative
path for deterministic cross-platform ordering. Every report/manifest entry
gains `relative_path`/`source_dir` provenance; identity
(`<stem>-<kind>-<sha8>.md`) stays content-hash-only -- folder is a signal,
never identity."""
from __future__ import annotations

import hashlib
from pathlib import Path

from docs.application.ingest import IngestService
from docs.domain.ingest_naming import ingested_output_path


class _FakeDetector:
    """Detects by filename lookup — no real magic-byte sniffing needed to
    exercise recursion/provenance (mirrors test_ingest_service.py's fake)."""

    def __init__(self, kind_by_name: dict[str, str]) -> None:
        self.kind_by_name = kind_by_name

    def detect(self, path: Path) -> str:
        return self.kind_by_name.get(path.name, "")


class _FakeHandler:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        self.calls.append(src)
        target = out_dir / f"{src.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


class _HashNamingHandler:
    """Mimics the real `<stem>-<kind>-<sha8>.md` naming convention (see
    tests/unit/application/test_ingest_idempotency.py) -- needed here so
    byte-identical sources genuinely collide on the same content-addressed
    output path regardless of which subfolder they live in."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        self.calls.append(src)
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


class _BatchingFakePdfHandler:
    """Simulates opendataloader-pdf's JVM look-ahead batching (design.md
    Decision 3): converting the FIRST sibling in a directory eagerly
    finalizes ALL its `.pdf` siblings' outputs in that same directory, not
    just its own."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        self.calls.append(src)
        for sibling in sorted(src.parent.glob("*.pdf")):
            sha8 = hashlib.sha256(sibling.read_bytes()).hexdigest()[:8]
            target = ingested_output_path(out_dir, sibling.stem, kind, sha8)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"# {sibling.name}", encoding="utf-8")
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        return ingested_output_path(out_dir, src.stem, kind, sha8)


# --- 7.1: nested file detected with relative_path provenance ------------


def test_nested_file_two_levels_deep_is_detected_with_relative_path(tmp_path: Path):
    inbox = tmp_path / "inbox"
    nested = inbox / "sub" / "deep"
    nested.mkdir(parents=True)
    (nested / "notes.md").write_text("# Notes", encoding="utf-8")
    handler = _FakeHandler()
    service = IngestService(_FakeDetector({"notes.md": "md"}), {"md": handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    entry = next(e for e in report["files"] if e["file"] == "notes.md")
    assert entry["relative_path"] == "sub/deep/notes.md"
    assert entry["source_dir"] == "sub/deep"
    assert entry["status"] == "ingested"
    assert handler.calls == [nested / "notes.md"]


# --- 7.2: unsupported nested / empty subfolder / equal-stem siblings ----


def test_unsupported_nested_file_reported_with_relative_path(tmp_path: Path):
    inbox = tmp_path / "inbox"
    nested = inbox / "weird"
    nested.mkdir(parents=True)
    (nested / "mystery.xyz").write_bytes(b"unknown bytes")
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    entry = next(e for e in report["files"] if e["file"] == "mystery.xyz")
    assert entry["status"] == "unsupported"
    assert entry["relative_path"] == "weird/mystery.xyz"


def test_empty_subfolder_produces_no_error_and_an_honest_empty_dir_marker(tmp_path: Path):
    # spec: "Empty subfolder produces no error" -- the run must not crash and
    # must never fabricate a fake file entry. design.md Decision 2 makes this
    # loud rather than silent: an honest {"relative_path": "<dir>/", "status":
    # "empty_dir"} marker, not a phantom FILE entry.
    inbox = tmp_path / "inbox"
    (inbox / "empty-sub").mkdir(parents=True)
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    assert report["processed"] == 0
    entry = next(e for e in report["files"] if e.get("relative_path") == "empty-sub/")
    assert entry["status"] == "empty_dir"


def test_nested_empty_subfolder_chain_reports_only_the_outermost_empty_dir(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "outer" / "inner").mkdir(parents=True)
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    empty_markers = [e["relative_path"] for e in report["files"] if e.get("status") == "empty_dir"]
    assert empty_markers == ["outer/"]


def test_equal_stem_byte_identical_files_in_different_subfolders_both_reported_distinctly(
    tmp_path: Path,
):
    # design.md Decision 2 "Collision semantics": equal stems in different
    # subfolders are two distinct report rows (distinct relative_path) even
    # when byte-identical content collapses them onto the same
    # content-addressed output -- the second becomes "batched" this run (or
    # "skipped" on a re-run), never silently merged or dropped.
    inbox = tmp_path / "inbox"
    (inbox / "a").mkdir(parents=True)
    (inbox / "b").mkdir(parents=True)
    (inbox / "a" / "readme.md").write_text("same content", encoding="utf-8")
    (inbox / "b" / "readme.md").write_text("same content", encoding="utf-8")
    handler = _HashNamingHandler()
    service = IngestService(_FakeDetector({"readme.md": "md"}), {"md": handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    by_rel = {e["relative_path"]: e for e in report["files"] if e["file"] == "readme.md"}
    assert set(by_rel) == {"a/readme.md", "b/readme.md"}
    assert by_rel["a/readme.md"]["status"] == "ingested"
    assert by_rel["b/readme.md"]["status"] == "batched"
    assert by_rel["a/readme.md"]["output"] == by_rel["b/readme.md"]["output"]
    assert len(handler.calls) == 1, "only the first-reached file should invoke the handler"

    second_report = service.ingest_inbox(inbox, tmp_path / "sections")
    by_rel2 = {e["relative_path"]: e for e in second_report["files"] if e["file"] == "readme.md"}
    assert by_rel2["a/readme.md"]["status"] == "skipped"
    assert by_rel2["b/readme.md"]["status"] == "skipped"


# --- 7.5: JVM look-ahead batching status vocabulary ----------------------


def test_jvm_lookahead_batch_first_sibling_ingested_second_batched_then_both_skipped_on_rerun(
    tmp_path: Path,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.pdf").write_bytes(b"pdf-content-a")
    (inbox / "b.pdf").write_bytes(b"pdf-content-b")
    handler = _BatchingFakePdfHandler()
    service = IngestService(_FakeDetector({"a.pdf": "pdf", "b.pdf": "pdf"}), {"pdf": handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    statuses = {e["file"]: e["status"] for e in report["files"] if e["file"].endswith(".pdf")}
    assert statuses == {"a.pdf": "ingested", "b.pdf": "batched"}
    assert [c.name for c in handler.calls] == ["a.pdf"], "look-ahead batch only invokes the handler once"

    second_report = service.ingest_inbox(inbox, tmp_path / "sections")
    second_statuses = {e["file"]: e["status"] for e in second_report["files"] if e["file"].endswith(".pdf")}
    assert second_statuses == {"a.pdf": "skipped", "b.pdf": "skipped"}


def test_jvm_lookahead_batch_scoped_per_directory_not_whole_tree(tmp_path: Path):
    # design.md Decision 3: batching is per-DIRECTORY, not whole-tree -- two
    # PDFs in DIFFERENT subfolders must never be treated as siblings of the
    # same batch, even with a handler that (like the fake above) looks at
    # `src.parent` for its batch scope.
    inbox = tmp_path / "inbox"
    (inbox / "dir1").mkdir(parents=True)
    (inbox / "dir2").mkdir(parents=True)
    (inbox / "dir1" / "one.pdf").write_bytes(b"pdf-one")
    (inbox / "dir2" / "two.pdf").write_bytes(b"pdf-two")
    handler = _BatchingFakePdfHandler()
    service = IngestService(_FakeDetector({"one.pdf": "pdf", "two.pdf": "pdf"}), {"pdf": handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    statuses = {e["file"]: e["status"] for e in report["files"]}
    # Both are "ingested" -- neither sibling's directory-scoped look-ahead
    # batch reaches across to the other directory.
    assert statuses == {"one.pdf": "ingested", "two.pdf": "ingested"}
    assert len(handler.calls) == 2
