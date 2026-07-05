# tests/unit/application/test_ingest_error_isolation.py
"""Fresh-context review WARNING 2 fix: a single unreadable/vanished file or a
handler failure must not abort the whole inbox scan (document-ingest spec:
`Tool-Failure Reporting` — errors MUST be reported, never crash the batch).
Scoped to per-file exception isolation only; PR6 task 6.3 owns the
configured fail-fast behavior for real per-type adapters."""
from pathlib import Path

from docs.application.ingest import IngestService


class _KindByExtensionDetector:
    def detect(self, path: Path) -> str:
        return path.suffix.lstrip(".")


class _RaisingHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        raise RuntimeError("boom: conversion tool exploded")


class _WorkingHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        target = out_dir / f"{src.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


def test_handler_exception_is_isolated_to_its_own_file(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "broken.docx").write_bytes(b"docx-bytes")
    (inbox / "fine.md").write_text("# fine", encoding="utf-8")
    service = IngestService(
        _KindByExtensionDetector(),
        {"docx": _RaisingHandler(), "md": _WorkingHandler()},
    )

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    assert report["processed"] == 2, "the whole batch must not abort"
    by_name = {entry["file"]: entry for entry in report["files"]}
    assert by_name["broken.docx"]["status"] == "error"
    assert "boom: conversion tool exploded" in by_name["broken.docx"]["cause"]
    assert by_name["fine.md"]["status"] == "ingested", "other files must still process"


def test_detection_report_is_still_written_when_a_file_errors(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "broken.docx").write_bytes(b"docx-bytes")
    service = IngestService(_KindByExtensionDetector(), {"docx": _RaisingHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")

    assert (inbox / "_detection.json").exists()


def test_detector_exception_is_isolated_and_recorded(tmp_path: Path):
    # Reviewer-verified real-world trigger: filetype.guess() raises
    # FileNotFoundError when a listed file vanishes before detection runs.
    class _RaisingDetector:
        def detect(self, path: Path) -> str:
            if path.name == "vanished.pdf":
                raise FileNotFoundError(f"{path} vanished before detection")
            return path.suffix.lstrip(".")

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "vanished.pdf").write_bytes(b"pdf-bytes")
    (inbox / "fine.md").write_text("# fine", encoding="utf-8")
    service = IngestService(_RaisingDetector(), {"md": _WorkingHandler()})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    by_name = {entry["file"]: entry for entry in report["files"]}
    assert by_name["vanished.pdf"]["status"] == "error"
    assert "vanished before detection" in by_name["vanished.pdf"]["cause"]
    assert by_name["fine.md"]["status"] == "ingested"
