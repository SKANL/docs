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
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter

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
    # Never flattened to markdown either -- a heuristic asset candidate is
    # excluded from the source walk until a human confirms a placement.
    assert all(e.get("file") != "cover.docx" for e in report["files"])
    assert {"relative_path": "cover.docx", "reason": "asset_candidate"} in report["ignored"]

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
    # Reported (never silently dropped), never flattened to markdown either.
    assert report["ignored"] == [
        {"relative_path": "images/guia/page-001-image-001.png", "reason": "asset_candidate"}
    ]


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


# --- Real-drop acceptance (coordinator-specified) -------------------------


def test_real_drop_cover_convention_asset_and_catalog_images_all_visible(tmp_path: Path):
    """Mirrors the user's real inbox shape: a top-level cover.docx (heuristic
    detection -> placement queue, never flattened to markdown), an
    inbox/assets/ file (convention routing), and a nested images/ folder
    (real python-docx image adapter, not a fake) with one genuinely
    parseable tiny PNG and one genuinely unparseable file -- everything
    queued/cataloged/reported, nothing silent."""
    inbox = tmp_path / "inbox"
    (inbox / "images" / "guia-referencia-estadia-tic").mkdir(parents=True)
    (inbox / "assets").mkdir(parents=True)

    (inbox / "cover.docx").write_bytes(b"docx-bytes")
    (inbox / "assets" / "logo.png").write_bytes(_PIXEL_PNG)
    images_dir = inbox / "images" / "guia-referencia-estadia-tic"
    (images_dir / "page-001-image-001.png").write_bytes(_PIXEL_PNG)
    (images_dir / "page-002-image-002.png").write_bytes(b"not-a-real-image")

    assets_dir = tmp_path / "assets"
    service = IngestService(
        _FakeDetector({"cover.docx": "docx"}),
        {"docx": _TextEchoHandler()},
        image_metadata=PythonDocxImageMetadataAdapter(),
    )

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    # cover.docx: never flattened to markdown, reported, queued.
    assert all(e.get("file") != "cover.docx" for e in report["files"])
    assert {"relative_path": "cover.docx", "reason": "asset_candidate"} in report["ignored"]
    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    assert queue["entries"]["cover.docx"]["proposed_kind"] == "cover"

    # inbox/assets/logo.png: routed unconditionally, physically copied.
    assert (assets_dir / "logo.png").read_bytes() == _PIXEL_PNG
    assert {"relative_path": "assets/logo.png", "reason": "assets_subtree"} in report["ignored"]

    # figure catalog: real parseable PNGs get real dimensions; the
    # genuinely unparseable file gets null dimensions -- NEVER guessed.
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    by_origin = {f["origin_relative_path"]: f for f in catalog["figures"]}
    assert by_origin["assets/logo.png"]["width_px"] == 1
    assert by_origin["assets/logo.png"]["height_px"] == 1
    parseable = by_origin["images/guia-referencia-estadia-tic/page-001-image-001.png"]
    assert parseable["width_px"] == 1
    assert parseable["height_px"] == 1
    unparseable = by_origin["images/guia-referencia-estadia-tic/page-002-image-002.png"]
    assert unparseable["width_px"] is None
    assert unparseable["height_px"] is None

    # Nothing silent: every dropped file is accounted for somewhere.
    reported_files = {e["relative_path"] for e in report["files"]}
    reported_ignored = {e["relative_path"] for e in report["ignored"]}
    assert reported_files | reported_ignored == {
        "cover.docx",
        "assets/logo.png",
        "images/guia-referencia-estadia-tic/page-001-image-001.png",
        "images/guia-referencia-estadia-tic/page-002-image-002.png",
    }
