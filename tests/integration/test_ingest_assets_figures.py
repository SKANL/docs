# tests/integration/test_ingest_assets_figures.py
"""Front F (design.md Decision 6; spec: asset-management) wired into
`IngestService.ingest_inbox`: verbatim-asset pre-ingest routing +
pending-placement queue + figure catalog. `inbox/assets/` files are
declared verbatim assets, routed unconditionally; heuristic-detected
assets elsewhere (image files, or a `.docx` in a cover/portada/anexo-visual
-named path) are only PROPOSED, never auto-routed, until externally
confirmed via `_placement-queue.json` (same external-confirmation contract
as the classification queue: survives re-scans, nothing auto-confirms)."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from docs.application.ingest import IngestService

_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


class _FakeDetector:
    def __init__(self, kind_by_name: dict[str, str]) -> None:
        self.kind_by_name = kind_by_name

    def detect(self, path: Path) -> str:
        return self.kind_by_name.get(path.name, "")


class _TextEchoHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return target


class _FakeImageMetadata:
    def read_dimensions(self, path: Path) -> tuple[int, int] | None:
        if path.suffix.lower() == ".png":
            return (1, 1)
        return None


def _service(kind_by_name: dict[str, str]) -> IngestService:
    return IngestService(
        _FakeDetector(kind_by_name),
        {"md": _TextEchoHandler(), "docx": _TextEchoHandler()},
        image_metadata=_FakeImageMetadata(),
    )


# --- 10.1: inbox/assets/ routed, bypasses markdown ingest ----------------


def test_declared_asset_is_routed_to_assets_dir_and_never_ingested(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "assets").mkdir(parents=True)
    (inbox / "assets" / "cover.docx").write_bytes(b"docx-bytes")
    assets_dir = tmp_path / "assets"
    service = _service({})

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    assert (assets_dir / "cover.docx").read_bytes() == b"docx-bytes"
    assert all(e.get("file") != "cover.docx" for e in report["files"])
    assert report["ignored"] == [{"relative_path": "assets/cover.docx", "reason": "assets_subtree"}]


def test_declared_asset_routing_is_skipped_gracefully_without_assets_dir(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "assets").mkdir(parents=True)
    (inbox / "assets" / "cover.docx").write_bytes(b"docx-bytes")
    service = _service({})

    report = service.ingest_inbox(inbox, tmp_path / "sections")  # no assets_dir

    assert all(e.get("file") != "cover.docx" for e in report["files"])


# --- 10.2/10.4: heuristic detection proposed, not auto-routed ------------


def test_top_level_cover_docx_heuristic_detected_and_queued_not_auto_routed(tmp_path: Path):
    # The real-world case: a top-level cover.docx (no enclosing folder at
    # all) is detected via its OWN filename, not just a folder name.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "cover.docx").write_bytes(b"docx-bytes")
    assets_dir = tmp_path / "assets"
    service = _service({"cover.docx": "docx"})

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    assert not (assets_dir / "cover.docx").exists()  # proposed, NOT auto-routed
    # Still a normal candidate source too (heuristic detection never STEALS
    # a legitimate content file -- design.md Decision 6a's own rationale).
    assert any(e.get("file") == "cover.docx" and e.get("status") == "ingested" for e in report["files"])

    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    entry = queue["entries"]["cover.docx"]
    assert entry["proposed_kind"] == "cover"
    assert entry["confirmed_placement"] is None


def test_image_file_anywhere_is_heuristically_proposed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "images" / "guia").mkdir(parents=True)
    (inbox / "images" / "guia" / "page-001-image-001.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    assert "images/guia/page-001-image-001.png" in queue["entries"]
    # No naming signal -- proposed_kind stays null, never invented.
    assert queue["entries"]["images/guia/page-001-image-001.png"]["proposed_kind"] is None
    assert report["ignored"] == []


def test_non_asset_like_file_is_not_proposed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "notes.md").write_text("# Notes", encoding="utf-8")
    service = _service({"notes.md": "md"})

    service.ingest_inbox(inbox, tmp_path / "sections")

    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    assert queue["entries"] == {}


# --- 10.5: confirmation round-trips into placements + physical routing --


def test_confirmed_placement_recorded_in_manifest_and_asset_physically_routed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "cover.docx").write_bytes(b"docx-bytes")
    assets_dir = tmp_path / "assets"
    service = _service({"cover.docx": "docx"})
    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    queue_path = inbox / "_placement-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["entries"]["cover.docx"]["confirmed_placement"] = "cover"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    assert (assets_dir / "cover.docx").read_bytes() == b"docx-bytes"
    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    placement = next(p for p in manifest["placements"] if p["relative_path"] == "cover.docx")
    assert placement["confirmed_placement"] == "cover"
    assert placement["structure_part"] == {"type": "cover_from_asset", "asset": "cover.docx"}


def test_unconfirmed_asset_reported_pending_never_auto_placed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "cover.docx").write_bytes(b"docx-bytes")
    service = _service({"cover.docx": "docx"})

    service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    placement = next(p for p in manifest["placements"] if p["relative_path"] == "cover.docx")
    assert placement["confirmed_placement"] is None
    assert placement["structure_part"] is None  # never auto-placed


def test_confirmation_survives_multiple_rescans(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "anexo-visual.docx").write_bytes(b"docx-bytes")
    service = _service({"anexo-visual.docx": "docx"})
    service.ingest_inbox(inbox, tmp_path / "sections")

    queue_path = inbox / "_placement-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["entries"]["anexo-visual.docx"]["confirmed_placement"] = "back"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    for _ in range(3):
        service.ingest_inbox(inbox, tmp_path / "sections")

    manifest = json.loads((inbox / "_source-manifest.json").read_text(encoding="utf-8"))
    placement = next(p for p in manifest["placements"] if p["relative_path"] == "anexo-visual.docx")
    assert placement["confirmed_placement"] == "back"
    assert placement["structure_part"] == {"type": "embed_docx", "asset": "anexo-visual.docx"}


# --- 10.6-10.9: figure catalog wiring -------------------------------------


def test_figure_catalog_written_with_hash_and_dimensions(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "images").mkdir(parents=True)
    (inbox / "images" / "page-001.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections")

    catalog_path = tmp_path / "sections" / "figure-catalog.json"
    assert catalog_path.exists()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    figure = catalog["figures"][0]
    assert figure["sha256"] == hashlib.sha256(_PIXEL_PNG).hexdigest()
    assert figure["width_px"] == 1
    assert figure["height_px"] == 1
    assert figure["origin_relative_path"] == "images/page-001.png"


def test_figure_catalog_includes_declared_asset_images(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "assets").mkdir(parents=True)
    (inbox / "assets" / "logo.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=tmp_path / "assets")

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"][0]["origin_relative_path"] == "assets/logo.png"


def test_figure_catalog_determinism_two_runs_byte_identical(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "images").mkdir(parents=True)
    (inbox / "images" / "page-001.png").write_bytes(_PIXEL_PNG)
    (inbox / "images" / "page-002.png").write_bytes(_PIXEL_PNG + b"\x00")
    service_a = _service({})
    service_a.ingest_inbox(inbox, tmp_path / "sections")
    first = (tmp_path / "sections" / "figure-catalog.json").read_bytes()

    service_b = _service({})
    service_b.ingest_inbox(inbox, tmp_path / "sections")
    second = (tmp_path / "sections" / "figure-catalog.json").read_bytes()

    assert first == second
    assert b"generated_at" not in first
