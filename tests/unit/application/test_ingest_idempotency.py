# tests/unit/application/test_ingest_idempotency.py
"""Idempotency contract (document-ingest spec: `Deterministic and Idempotent
Ingest`). Unlike test_ingest_service.py's routing-only `_FakeHandler` (which
writes `<stem>.md` and is not meant to prove idempotency), `_HashNamingHandler`
here follows the real `<stem>-<sha8>.md` naming convention future adapters
(PR6) will use, so it can prove: (1) a second run over an unchanged source
does not re-invoke the handler, (2) changed content produces a fresh output
without touching or duplicating the previous one — matching the
"already recorded with matching hash" contract in design.md via the
deterministic output path itself (no separate manifest lookup needed).
"""
import hashlib
from pathlib import Path

from docs.application.ingest import IngestService


class _FixedKindDetector:
    def detect(self, path: Path) -> str:
        return "docx"


class _HashNamingHandler:
    """Mimics the real `<stem>-<kind>-<sha8>.md` naming convention every
    per-kind adapter (PR6) uses — `kind` is the detector-resolved value
    `SourceIngestPort.ingest(src, out_dir, kind)` passes in (fresh-review
    FINDING 1: identity must come from the router's resolved kind, not be
    re-derived from the source's own extension)."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.calls: list[Path] = []

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        self.calls.append(src)
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


class _KindByExtensionDetector:
    def detect(self, path: Path) -> str:
        return path.suffix.lstrip(".")


def test_unchanged_source_is_not_re_ingested_on_second_run(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"stable content")
    handler = _HashNamingHandler("docx")
    service = IngestService(_FixedKindDetector(), {"docx": handler})

    first = service.ingest_inbox(inbox, tmp_path / "sections")
    second = service.ingest_inbox(inbox, tmp_path / "sections")

    assert len(handler.calls) == 1, "handler must run once, not on every scan"
    assert first["files"][0]["status"] == "ingested"
    assert second["files"][0]["status"] == "skipped"
    assert first["files"][0]["output"] == second["files"][0]["output"]


def test_changed_content_triggers_fresh_ingest_without_touching_prior_output(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "a.docx"
    src.write_bytes(b"version one")
    handler = _HashNamingHandler("docx")
    service = IngestService(_FixedKindDetector(), {"docx": handler})

    first = service.ingest_inbox(inbox, tmp_path / "sections")
    first_output = Path(first["files"][0]["output"])
    first_bytes = first_output.read_bytes()

    src.write_bytes(b"version two - changed")
    second = service.ingest_inbox(inbox, tmp_path / "sections")
    second_output = Path(second["files"][0]["output"])

    assert len(handler.calls) == 2, "changed content must trigger a fresh ingest"
    assert second["files"][0]["status"] == "ingested"
    assert second_output != first_output, "each distinct hash gets its own deterministic path"
    assert first_output.exists(), "prior output must not be deleted or corrupted"
    assert first_output.read_bytes() == first_bytes, "prior output content must be untouched"


def test_partially_processed_inbox_only_converts_unprocessed_files(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "already.docx").write_bytes(b"already ingested content")
    (inbox / "new.docx").write_bytes(b"brand new content")
    handler = _HashNamingHandler("docx")
    service = IngestService(_FixedKindDetector(), {"docx": handler})

    service.ingest_inbox(inbox, tmp_path / "sections")
    handler.calls.clear()
    (inbox / "new2.docx").write_bytes(b"another new file")

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    ingested_names = {call.name for call in handler.calls}
    assert ingested_names == {"new2.docx"}, "only the newly added file should be (re-)converted"
    statuses = {entry["file"]: entry["status"] for entry in report["files"]}
    assert statuses["already.docx"] == "skipped"
    assert statuses["new.docx"] == "skipped"
    assert statuses["new2.docx"] == "ingested"


def test_same_stem_and_hash_but_different_kind_are_not_conflated(tmp_path: Path):
    # Fresh-context review repro: readme.md and readme.txt with byte-identical
    # bodies share `stem` AND `sha8`. Keying the skip-check on `stem+sha8`
    # alone silently drops the second file as a false "skipped" — its handler
    # is never invoked. Identity must be (stem, detected kind, content hash).
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    body = b"identical body, only the extension differs"
    (inbox / "readme.md").write_bytes(body)
    (inbox / "readme.txt").write_bytes(body)
    md_handler = _HashNamingHandler("md")
    txt_handler = _HashNamingHandler("txt")
    service = IngestService(_KindByExtensionDetector(), {"md": md_handler, "txt": txt_handler})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    assert len(md_handler.calls) == 1, "the .md source must be ingested"
    assert len(txt_handler.calls) == 1, "the .txt source must ALSO be ingested, not silently skipped"
    statuses = {entry["file"]: entry["status"] for entry in report["files"]}
    assert statuses["readme.md"] == "ingested"
    assert statuses["readme.txt"] == "ingested"
    outputs = {entry["file"]: entry["output"] for entry in report["files"]}
    assert outputs["readme.md"] != outputs["readme.txt"], "same stem+hash across kinds must not collide"
