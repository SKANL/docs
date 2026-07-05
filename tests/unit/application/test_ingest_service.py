# tests/unit/application/test_ingest_service.py
import json
from pathlib import Path

from docs.application.ingest import IngestService


class _FakeDetector:
    """Detects by filename lookup — no real magic-byte sniffing needed to
    exercise routing (that's covered by test_source_type_detector.py)."""

    def __init__(self, kind_by_name: dict[str, str]) -> None:
        self.kind_by_name = kind_by_name

    def detect(self, path: Path) -> str:
        return self.kind_by_name.get(path.name, "")


class _FakeHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def ingest(self, src: Path, out_dir: Path) -> Path:
        self.calls.append((src, out_dir))
        target = out_dir / f"{src.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


class _RaisingHandler:
    """Simulates a real per-type adapter (PR6) failing mid-conversion."""

    def ingest(self, src: Path, out_dir: Path) -> Path:
        raise RuntimeError("boom: tool failed mid-conversion")


def test_routes_detected_kind_to_matching_handler_stub(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"docx-bytes")
    handler = _FakeHandler()
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    assert report["processed"] == 1
    assert handler.calls, "handler for the detected kind must be invoked"
    entry = report["files"][0]
    assert entry["kind"] == "docx"
    assert entry["status"] == "ingested"


def test_unsupported_type_is_recorded_and_never_raises(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "b.xyz").write_bytes(b"unrecognizable bytes")
    service = IngestService(_FakeDetector({}), {})  # no handlers registered

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    entry = report["files"][0]
    assert entry["status"] == "unsupported"


def test_unsupported_type_does_not_invoke_any_handler(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c.xyz").write_bytes(b"unrecognizable bytes")
    handler = _FakeHandler()
    service = IngestService(_FakeDetector({}), {"docx": handler})

    service.ingest_inbox(inbox, tmp_path / "sections")

    assert handler.calls == []


def test_empty_inbox_reports_zero_files_processed_no_error(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    assert report == {"processed": 0, "files": []}


def test_missing_inbox_dir_reports_zero_files_processed_no_error(tmp_path: Path):
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(tmp_path / "missing-inbox", tmp_path / "sections")

    assert report["processed"] == 0
    assert report["files"] == []


def test_writes_detection_report_to_inbox_with_stable_key_ordering(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"docx-bytes")
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": _FakeHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")

    detection_path = inbox / "_detection.json"
    assert detection_path.exists()
    raw = detection_path.read_text(encoding="utf-8")
    assert "generated_at" not in raw  # determinism: no timestamps
    payload = json.loads(raw)
    assert payload["processed"] == 1


def test_handler_failure_preserves_detected_kind_in_error_entry(tmp_path: Path):
    # PR6 fresh-review carry-forward (b): a kind already resolved by the
    # detector must survive into the `status: "error"` entry instead of the
    # unconditional `"kind": "unknown"` the pre-PR6 code produced.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "broken.pdf").write_bytes(b"pdf-bytes")
    service = IngestService(_FakeDetector({"broken.pdf": "pdf"}), {"pdf": _RaisingHandler()})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    entry = report["files"][0]
    assert entry["status"] == "error"
    assert entry["kind"] == "pdf"
    assert "boom" in entry["cause"]


def test_rescan_ignores_previously_written_detection_report(tmp_path: Path):
    # `_detection.json` is written into the inbox dir itself; a second scan
    # must not treat it as a source file to ingest.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"docx-bytes")
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": _FakeHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")
    second_report = service.ingest_inbox(inbox, tmp_path / "sections")

    names = [entry["file"] for entry in second_report["files"]]
    assert "_detection.json" not in names
