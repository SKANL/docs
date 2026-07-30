# tests/integration/test_ingest_content_classification.py
"""Content-based source classification wired into `IngestService`
(design.md item D, PR4; spec: document-ingest "Content-Based Source
Classification with Confidence Threshold"). A flat dump of arbitrarily
NAMED files (no folder-lexicon signal) is classified by an injected
`ContentProbePort`'s already-probed content signals -- high confidence
acts automatically; medium/low confidence is HELD for confirmation, never
silently defaulted, in BOTH draft and strict mode (this is stricter than
the pre-existing folder/filename-only gate, which used to admit any
unconfirmed proposal with a PENDIENTE gap in draft mode)."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.ingest import IngestService
from docs.domain.ports.content_probe_port import ContentSignals


class _FakeDetector:
    def __init__(self, kind_by_name: dict[str, str]) -> None:
        self.kind_by_name = kind_by_name

    def detect(self, path: Path) -> str:
        return self.kind_by_name.get(path.name, "")


class _TextEchoHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        import hashlib

        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return target


class _FakeContentProbe:
    """Injected `ContentProbePort` double -- keyed by filename, mirroring
    `_FakeDetector`'s shape (the real `FilesystemContentProbeAdapter` is
    covered separately in `test_content_probe_adapter.py`)."""

    def __init__(self, signals_by_name: dict[str, ContentSignals]) -> None:
        self.signals_by_name = signals_by_name

    def probe(self, path: Path) -> ContentSignals:
        return self.signals_by_name.get(path.name, ContentSignals())


def _service(kind_by_name: dict[str, str], signals_by_name: dict[str, ContentSignals]) -> IngestService:
    return IngestService(
        _FakeDetector(kind_by_name),
        {"md": _TextEchoHandler(), "pdf": _TextEchoHandler()},
        content_probe=_FakeContentProbe(signals_by_name),
    )


def test_high_confidence_content_classification_acts_automatically_on_arbitrary_name(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "9f3ac1.pdf").write_text("contenido arbitrario", encoding="utf-8")
    service = _service(
        {"9f3ac1.pdf": "pdf"},
        {"9f3ac1.pdf": ContentSignals(pdf_title="Manual de Normativa Interna")},
    )

    service.ingest_inbox(inbox, tmp_path / "sections", strict=False)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "9f3ac1.pdf")
    assert entry["proposed_role"] == "normative"
    assert entry["confidence"] == "high"
    assert entry["role_status"]["blocked"] is False
    assert entry["role_status"]["effective_role"] == "normative"


def test_medium_confidence_content_classification_is_held_not_defaulted_in_draft_mode(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "8b21ee.pdf").write_text("contenido arbitrario", encoding="utf-8")
    service = _service(
        {"8b21ee.pdf": "pdf"},
        {"8b21ee.pdf": ContentSignals(head_keywords=("referencia",))},
    )

    report = service.ingest_inbox(inbox, tmp_path / "sections", strict=False)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "8b21ee.pdf")
    assert entry["confidence"] == "medium"
    assert entry["role_status"]["blocked"] is True
    assert entry["role_status"]["effective_role"] is None
    # Never crashes ingest (spec scenario: "ingest completes without crashing").
    assert report["processed"] == 1
    queue = json.loads((inbox / "_classification-queue.json").read_text(encoding="utf-8"))
    assert queue["entries"]["8b21ee.pdf"]["proposed_role"] == "example"


def test_low_confidence_arbitrary_name_with_no_content_signal_is_held_not_defaulted(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "random.pdf").write_text("contenido sin senal alguna", encoding="utf-8")
    service = _service({"random.pdf": "pdf"}, {})

    service.ingest_inbox(inbox, tmp_path / "sections", strict=False)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "random.pdf")
    assert entry["proposed_role"] == "unknown"
    assert entry["confidence"] == "low"
    assert entry["role_status"]["blocked"] is True
    assert entry["role_status"]["effective_role"] is None


def test_flat_dump_mixed_confidence_strong_routed_weak_queued(tmp_path: Path):
    # spec scenario: "Flat arbitrary dump with mixed confidence".
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "aaa111.pdf").write_text("fuerte", encoding="utf-8")
    (inbox / "bbb222.pdf").write_text("debil", encoding="utf-8")
    service = _service(
        {"aaa111.pdf": "pdf", "bbb222.pdf": "pdf"},
        {"aaa111.pdf": ContentSignals(pdf_title="Manual de Normativa Interna")},
    )

    service.ingest_inbox(inbox, tmp_path / "sections", strict=False)

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    strong = next(s for s in manifest["sources"] if s["relative_path"] == "aaa111.pdf")
    weak = next(s for s in manifest["sources"] if s["relative_path"] == "bbb222.pdf")
    assert strong["role_status"]["effective_role"] == "normative"
    assert weak["role_status"]["effective_role"] is None
    assert weak["role_status"]["blocked"] is True


def test_confirmed_role_still_overrides_a_held_low_confidence_classification(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "random.pdf").write_text("contenido sin senal alguna", encoding="utf-8")
    service = _service({"random.pdf": "pdf"}, {})
    service.ingest_inbox(inbox, tmp_path / "sections")
    queue_path = inbox / "_classification-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["entries"]["random.pdf"]["confirmed_role"] = "evidence"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["relative_path"] == "random.pdf")
    assert entry["role_status"]["blocked"] is False
    assert entry["role_status"]["effective_role"] == "evidence"
