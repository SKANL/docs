# tests/unit/application/test_ingest_service.py
import hashlib
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

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        self.calls.append((src, out_dir))
        target = out_dir / f"{src.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {src.name}", encoding="utf-8")
        return target


class _RaisingHandler:
    """Simulates a real per-type adapter (PR6) failing mid-conversion."""

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        raise RuntimeError("boom: tool failed mid-conversion")


class _FakeWriter:
    """Fake `IngestArtifactWriter` (design.md Decision 9) proving
    `IngestService` DELEGATES its JSON artifact writes through the injected
    port instead of writing directly -- atomicity itself is
    `FilesystemIngestArtifactWriter`'s own concern, tested separately in
    tests/unit/infrastructure/test_filesystem_ingest_artifact_writer.py."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict]] = []

    def write_json(self, path: Path, payload: dict) -> None:
        self.calls.append((path, payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


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

    # media_cleanup added in Front B (design.md Decision 8 #13); ignored
    # added in Front C (design.md Decision 2) -- both always present, empty
    # when there is nothing to report.
    assert report == {
        "processed": 0,
        "files": [],
        "ignored": [],
        "media_cleanup": {"removed": [], "refused": []},
    }


def test_missing_inbox_dir_reports_zero_files_processed_no_error(tmp_path: Path):
    service = IngestService(_FakeDetector({}), {})

    report = service.ingest_inbox(tmp_path / "missing-inbox", tmp_path / "sections")

    assert report["processed"] == 0
    assert report["files"] == []


# --- Item F (PR5): wire the PDF render adapter into ingest ----------------


class _FakePdfHandler:
    """Writes the deterministic `<stem>-pdf-<sha8>.md` name a real PDF
    handler (OpendataloaderPdfAdapter) would, optionally alongside a
    `_media/` sibling directory -- so the render-gate check (paired `_media`
    absent/empty) has something real to inspect."""

    def __init__(self, with_media: bool = False) -> None:
        self.with_media = with_media

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {src.name}", encoding="utf-8")
        if self.with_media:
            media_dir = out_dir / f"{src.stem}-{kind}-{sha8}_media"
            media_dir.mkdir(exist_ok=True)
            (media_dir / "image1.png").write_bytes(b"raster-bytes")
        return target


class _FakePdfRender:
    """Fake `PdfRenderPort`: records calls, writes N deterministic PNGs."""

    def __init__(self, page_count: int = 2) -> None:
        self.page_count = page_count
        self.calls: list[Path] = []

    def render_pages(
        self, pdf_path: Path, out_dir: Path, dpi: int = 150, pages: str | None = None, autotrim: bool = True
    ) -> list[Path]:
        self.calls.append(Path(pdf_path))
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for index in range(self.page_count):
            dest = out_dir / f"{Path(pdf_path).stem}-p{index + 1:02d}.png"
            dest.write_bytes(f"page-{index + 1}".encode())
            written.append(dest)
        return written


def test_pdf_render_adds_figures_for_vector_only_pdf_with_no_extracted_media(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    assets_dir = tmp_path / "assets"
    fake_render = _FakePdfRender(page_count=2)
    service = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler(with_media=False)},
        pdf_render=fake_render,
    )

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    assert fake_render.calls == [inbox / "diagram.pdf"]
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    origins = sorted(f["origin_relative_path"] for f in catalog["figures"])
    assert origins == ["assets/figures/diagram-p01.png", "assets/figures/diagram-p02.png"]
    assert (assets_dir / "figures" / "diagram-p01.png").exists()


def test_pdf_render_skips_pdf_that_already_yielded_raster_media(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "scanned.pdf").write_bytes(b"raster-pdf-bytes")
    fake_render = _FakePdfRender()
    service = IngestService(
        _FakeDetector({"scanned.pdf": "pdf"}),
        {"pdf": _FakePdfHandler(with_media=True)},
        pdf_render=fake_render,
    )

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=tmp_path / "assets")

    assert fake_render.calls == []  # raster already extracted -- never double-count
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"] == []


def test_pdf_render_toolchain_absent_skips_gracefully_and_warns(tmp_path: Path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    service = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler(with_media=False)},
        pdf_render=None,  # toolchain absent, exactly as `Deps` degrades it
    )

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=tmp_path / "assets")

    assert report["files"][0]["status"] == "ingested"  # document still assembles
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"] == []
    assert "WARN" in capsys.readouterr().err


def test_pdf_render_figure_catalog_deterministic_across_runs(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    assets_dir = tmp_path / "assets"

    service_a = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler(with_media=False)},
        pdf_render=_FakePdfRender(page_count=2),
    )
    service_a.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)
    first = (tmp_path / "sections" / "figure-catalog.json").read_bytes()

    service_b = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler(with_media=False)},
        pdf_render=_FakePdfRender(page_count=2),
    )
    service_b.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)
    second = (tmp_path / "sections" / "figure-catalog.json").read_bytes()

    assert first == second
    ids = [f["id"] for f in json.loads(first)["figures"]]
    assert ids == sorted(ids)


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


def test_writes_source_manifest_with_provenance_entries(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "sub").mkdir(parents=True)
    (inbox / "sub" / "a.docx").write_bytes(b"docx-bytes")
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": _FakeHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest_path = inbox / "_source-manifest.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["duplicates"] == []
    entry = payload["sources"][0]
    # role/duplicate fields (Front D/E) are asserted in their own dedicated
    # test suites (test_source_role.py, test_ingest_roles_duplicates.py) --
    # this test stays scoped to provenance (Front C).
    assert entry["file"] == "a.docx"
    assert entry["relative_path"] == "sub/a.docx"
    assert entry["source_dir"] == "sub"
    assert entry["kind"] == "docx"
    assert entry["status"] == "ingested"
    assert len(entry["sha256"]) == 64
    assert entry["output"]


def test_ingest_inbox_delegates_json_artifact_writes_to_injected_writer(tmp_path: Path):
    # design.md Decision 9 (IngestArtifactWriter port) -- IngestService must
    # DELEGATE its JSON artifact writes through an injected writer rather
    # than always writing directly, so the atomic seam is real and testable.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"docx-bytes")
    writer = _FakeWriter()
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": _FakeHandler()}, writer=writer)

    service.ingest_inbox(inbox, tmp_path / "sections")

    written_names = {path.name for path, _ in writer.calls}
    assert written_names == {
        "_detection.json",
        "_source-manifest.json",
        "_classification-queue.json",
        "_placement-queue.json",
        "figure-catalog.json",
    }


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


# --- Item K (PR8): cross-source conflict detection -------------------------


class _TextPassthroughHandler:
    """Writes the SOURCE text verbatim as the ingested output -- conflict
    detection reads the ingested `.md` text (design.md K: "it already has
    each ingested source's text available"), not the raw pre-conversion
    bytes, so this fake stands in for a real converter that preserves
    prose."""

    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        target = out_dir / f"{src.stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return target


def test_ingest_inbox_detects_cross_source_conflict_and_warns(tmp_path: Path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "proyecto.md").write_text("El backend usa bun.js y TypeScript.", encoding="utf-8")
    (inbox / "technical-design.md").write_text(
        "El backend está construido en PHP con Laravel.", encoding="utf-8"
    )
    service = IngestService(
        _FakeDetector({"proyecto.md": "markdown", "technical-design.md": "markdown"}),
        {"markdown": _TextPassthroughHandler()},
    )

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["conflicts"]) == 1
    conflict = manifest["conflicts"][0]
    assert conflict["group"] == "backend_runtime"
    assert sorted(conflict["sources"]) == ["proyecto.md", "technical-design.md"]
    assert "WARN" in capsys.readouterr().err


def test_ingest_inbox_no_conflict_manifest_conflicts_empty(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.md").write_text("Todo tranquilo por aquí.", encoding="utf-8")
    service = IngestService(_FakeDetector({"a.md": "markdown"}), {"markdown": _TextPassthroughHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    assert manifest["conflicts"] == []


# --- Item G (PR8): intake/gap report ----------------------------------------


def test_ingest_inbox_writes_intake_report_md(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.docx").write_bytes(b"docx-bytes")
    service = IngestService(_FakeDetector({"a.docx": "docx"}), {"docx": _FakeHandler()})

    service.ingest_inbox(inbox, tmp_path / "sections")

    report_path = inbox / "intake-report.md"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "## Encontrado" in content
    assert "a.docx" in content


def test_ingest_inbox_intake_report_includes_gap_report_and_ledger_when_present(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    sections = tmp_path / "sections"
    sections.mkdir()
    (sections / "gap-report.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "context_gaps": [{"topic_id": "objetivo", "missing": ["descripcion"]}],
                "section_gaps": [],
            }
        ),
        encoding="utf-8",
    )
    (sections / "00-fact-ledger.md").write_text(
        "- PENDIENTE: horas totales\n- Hecho confirmado.\n", encoding="utf-8"
    )
    service = IngestService(_FakeDetector({}), {})

    service.ingest_inbox(inbox, sections)

    content = (inbox / "intake-report.md").read_text(encoding="utf-8")
    assert "`objetivo`: descripcion" in content
    assert "PENDIENTE: horas totales" in content
    assert "Hecho confirmado." not in content


def test_ingest_inbox_intake_report_absent_when_no_inbox_dir(tmp_path: Path):
    service = IngestService(_FakeDetector({}), {})

    service.ingest_inbox(tmp_path / "missing-inbox", tmp_path / "sections")

    assert not (tmp_path / "missing-inbox" / "intake-report.md").exists()
