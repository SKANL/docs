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
import struct
import zlib
from pathlib import Path

from docs.application.ingest import IngestService
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter

_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _solid_png(width: int, height: int) -> bytes:
    """A minimal, genuinely-parseable RGB PNG at the given size (no Pillow
    dependency -- same struct+zlib construction as
    `_malformed_but_pillow_openable_png` below). Used wherever a figure-size-
    filter test (`MIN_FIGURE_DIMENSION_PX`) needs real dimensions above the
    threshold rather than the 1x1 `_PIXEL_PNG`."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"".join(b"\x00" + bytes([180, 180, 180] * width) for _ in range(height))
    idat = zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _malformed_but_pillow_openable_png() -> bytes:
    """A hand-built 4x4 RGBA PNG whose IDAT chunk declares a length 8 bytes
    longer than its actual compressed data (a "raw"/non-Pillow encoder's
    off-by-N framing bug). Pillow's decoder tolerates this -- it scans the
    zlib stream to its own natural end and ignores the declared-length
    overshoot -- but python-docx's minimal `docx.image.png` chunk-offset
    walker trusts the declared length literally, overruns past the real
    end of file while reading the next chunk header, and raises
    `docx.image.exceptions.UnexpectedEndOfFileError` -- a bare `Exception`
    subclass raised with NO arguments, so `str(exc) == ""`. This is a real,
    deterministic reproduction of the reported clean-room bug (confirmed via
    both `PIL.Image.open(...).load()` succeeding and `docx.image.image.Image.
    from_file(...)` raising), not a synthetic/injected failure."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    def chunk_with_declared_len(tag: bytes, data: bytes, declared_len: int) -> bytes:
        return struct.pack(">I", declared_len) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    width = height = 4
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = b"".join(b"\x00" + bytes([255, 0, 0, 255] * width) for _ in range(height))
    idat_data = zlib.compress(raw)
    idat_chunk = chunk_with_declared_len(b"IDAT", idat_data, len(idat_data) + 8)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + idat_chunk + chunk(b"IEND", b"")


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
        # 200x200: comfortably above `MIN_FIGURE_DIMENSION_PX` (100) so the
        # mechanical size filter (ADR-2) never masks the role-based
        # assertions these fixture-driven tests exist to check.
        if path.suffix.lower() == ".png":
            return (200, 200)
        return None


class _FakeSubThresholdImageMetadata:
    def read_dimensions(self, path: Path) -> tuple[int, int] | None:
        # 50x50: below `MIN_FIGURE_DIMENSION_PX` (100) so the size filter
        # (ADR-2) drops the rendered page after render_pages already wrote it.
        return (50, 50) if path.suffix.lower() == ".png" else None


class _FakePdfRender:
    """Fake `PdfRenderPort`: writes N deterministic PNGs (mirrors
    `tests/unit/application/test_ingest_service.py`'s copy)."""

    def __init__(self, page_count: int = 1) -> None:
        self.page_count = page_count

    def render_pages(
        self, pdf_path: Path, out_dir: Path, dpi: int = 150, pages: str | None = None, autotrim: bool = True
    ) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for index in range(self.page_count):
            dest = out_dir / f"{Path(pdf_path).stem}-p{index + 1:02d}.png"
            dest.write_bytes(_PIXEL_PNG)
            written.append(dest)
        return written


class _FakePdfHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# pdf", encoding="utf-8")
        return target


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


def test_unproposable_image_is_cataloged_as_a_figure_not_queued_for_placement(tmp_path: Path):
    """A heuristic image with no placement signal has nothing to confirm: it is
    a figure (it lands in the figure catalog), not a document-structure asset.
    Queueing it would flood the confirmation queue with unanswerable entries --
    the real drop produced 59 such nulls against 1 real cover. It is still kept
    out of markdown ingest and still reported, just never queued."""
    # Folder "otros" ("others") deliberately carries NO role-lexicon signal
    # (unlike "guia") -- this test is about placement-queue behavior, not
    # role filtering (that is `test_standalone_guia_role_image_excluded_*`
    # below), so its fixture must not incidentally collide with ADR-2's
    # mechanical role filter.
    inbox = tmp_path / "inbox"
    (inbox / "images" / "otros").mkdir(parents=True)
    (inbox / "images" / "otros" / "page-001-image-001.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    report = service.ingest_inbox(inbox, tmp_path / "sections")

    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    assert queue["entries"] == {}
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert [f["origin_relative_path"] for f in catalog["figures"]] == [
        "images/otros/page-001-image-001.png"
    ]
    # Reported (never silently dropped), never flattened to markdown either.
    assert report["ignored"] == [
        {"relative_path": "images/otros/page-001-image-001.png", "reason": "asset_candidate"}
    ]


def test_declared_asset_without_a_guessable_kind_is_still_queued(tmp_path: Path):
    """Putting a file in inbox/assets/ IS the declaration -- the harness must
    still ask where it goes even when the filename carries no placement signal.
    This is the line between "nothing to confirm" (heuristic, unqueued above)
    and "declared, placement unknown" (queued here)."""
    inbox = tmp_path / "inbox"
    (inbox / "assets").mkdir(parents=True)
    (inbox / "assets" / "diagrama.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections")

    queue = json.loads((inbox / "_placement-queue.json").read_text(encoding="utf-8"))
    assert queue["entries"] == {
        "assets/diagrama.png": {"proposed_kind": None, "confirmed_placement": None}
    }


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
    assert figure["width_px"] == 200
    assert figure["height_px"] == 200
    # No `assets_dir` passed -> no stable-path copy (ADR-3 is gated on it) --
    # origin_relative_path stays the raw inbox-relative path.
    assert figure["origin_relative_path"] == "images/page-001.png"


def test_figure_catalog_includes_declared_asset_images(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "assets").mkdir(parents=True)
    (inbox / "assets" / "logo.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=tmp_path / "assets")

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    # `assets_dir` IS passed -> the surviving declared-asset image gets the
    # ADR-3 stable-path copy + origin_relative_path rewrite.
    sha8 = hashlib.sha256(_PIXEL_PNG).hexdigest()[:8]
    assert catalog["figures"][0]["origin_relative_path"] == f"assets/figures/fig-{sha8}.png"


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

    # `_solid_png` (>=100px, real+parseable) rather than the 1x1 `_PIXEL_PNG`
    # -- these two must survive ADR-2's size filter to prove the rest of the
    # acceptance scenario (stable-path copy, dims-in-catalog).
    logo_bytes = _solid_png(150, 150)
    parseable_bytes = _solid_png(120, 130)
    unparseable_bytes = b"not-a-real-image"

    (inbox / "cover.docx").write_bytes(b"docx-bytes")
    (inbox / "assets" / "logo.png").write_bytes(logo_bytes)
    images_dir = inbox / "images" / "guia-referencia-estadia-tic"
    (images_dir / "page-001-image-001.png").write_bytes(parseable_bytes)
    (images_dir / "page-002-image-002.png").write_bytes(unparseable_bytes)

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

    # inbox/assets/logo.png: still routed unconditionally to assets_dir root
    # (Front F declared-asset routing -- unrelated to the figure-catalog
    # stable-path copy below, a separate copy of the same bytes).
    assert (assets_dir / "logo.png").read_bytes() == logo_bytes
    assert {"relative_path": "assets/logo.png", "reason": "assets_subtree"} in report["ignored"]

    # figure catalog: real parseable PNGs get real dimensions AND the ADR-3
    # stable `assets/figures/fig-<sha8>.png` origin; the genuinely
    # unparseable file gets null dimensions -- NEVER guessed -- but is still
    # copied to its own stable path (null-dims fail-open per ADR-2).
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    by_sha8 = {f["sha256"][:8]: f for f in catalog["figures"]}
    logo_sha8 = hashlib.sha256(logo_bytes).hexdigest()[:8]
    parseable_sha8 = hashlib.sha256(parseable_bytes).hexdigest()[:8]
    unparseable_sha8 = hashlib.sha256(unparseable_bytes).hexdigest()[:8]

    logo_figure = by_sha8[logo_sha8]
    assert logo_figure["width_px"] == 150
    assert logo_figure["height_px"] == 150
    assert logo_figure["origin_relative_path"] == f"assets/figures/fig-{logo_sha8}.png"
    assert (assets_dir / "figures" / f"fig-{logo_sha8}.png").read_bytes() == logo_bytes

    parseable = by_sha8[parseable_sha8]
    assert parseable["width_px"] == 120
    assert parseable["height_px"] == 130
    assert parseable["origin_relative_path"] == f"assets/figures/fig-{parseable_sha8}.png"

    unparseable = by_sha8[unparseable_sha8]
    assert unparseable["width_px"] is None
    assert unparseable["height_px"] is None
    assert unparseable["origin_relative_path"] == f"assets/figures/fig-{unparseable_sha8}.png"

    # Nothing silent: every dropped file is accounted for somewhere.
    reported_files = {e["relative_path"] for e in report["files"]}
    reported_ignored = {e["relative_path"] for e in report["ignored"]}
    assert reported_files | reported_ignored == {
        "cover.docx",
        "assets/logo.png",
        "images/guia-referencia-estadia-tic/page-001-image-001.png",
        "images/guia-referencia-estadia-tic/page-002-image-002.png",
    }


# --- HIGH robustness fix: a crashing image must not abort the whole batch --


def test_image_metadata_crash_is_isolated_warns_and_still_catalogs_other_images(
    tmp_path: Path, capsys
) -> None:
    """A malformed-but-Pillow-openable image makes python-docx's minimal PNG
    parser raise `UnexpectedEndOfFileError` (empty message) instead of one
    of `read_dimensions`'s already-handled exception types. Before the fix,
    this exception escaped `ingest_inbox` entirely and crashed the whole
    scan. It must instead degrade exactly like a known-unparseable image
    (null dimensions, still cataloged) while surfacing a non-empty WARN."""
    inbox = tmp_path / "inbox"
    (inbox / "images").mkdir(parents=True)
    (inbox / "images" / "bad.png").write_bytes(_malformed_but_pillow_openable_png())
    # >=100px (`_solid_png`, not the 1x1 `_PIXEL_PNG`) so it survives ADR-2's
    # size filter and this test stays about the CRASH-isolation guarantee,
    # not an incidental size-filter drop.
    (inbox / "images" / "good.png").write_bytes(_solid_png(120, 90))
    (inbox / "notes.md").write_text("# hello", encoding="utf-8")
    service = IngestService(
        _FakeDetector({"notes.md": "md"}),
        {"md": _TextEchoHandler()},
        image_metadata=PythonDocxImageMetadataAdapter(),
    )

    report = service.ingest_inbox(inbox, tmp_path / "sections")  # must not raise

    # The other source still ingests normally.
    assert any(e["file"] == "notes.md" and e["status"] == "ingested" for e in report["files"])

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    by_origin = {f["origin_relative_path"]: f for f in catalog["figures"]}
    # The crashing image is still cataloged (sha256 known from its bytes),
    # just without dimensions -- same shape as a genuinely-unparseable file.
    assert by_origin["images/bad.png"]["width_px"] is None
    assert by_origin["images/bad.png"]["height_px"] is None
    # The OTHER image is unaffected -- real dimensions still read.
    assert by_origin["images/good.png"]["width_px"] == 120
    assert by_origin["images/good.png"]["height_px"] == 90

    stderr = capsys.readouterr().err
    assert "images/bad.png" in stderr
    assert "UnexpectedEndOfFileError" in stderr  # non-empty diagnostic, not "ERROR: "


# --- S2 (smart-figure-embedding): role resolution, filter, stable-path copy,
# and confirmed-role propagation wired into `_build_figure_catalog`
# (design.md ADR-1/ADR-2/ADR-3; tasks.md 2.1-2.4) --------------------------


def test_standalone_guia_role_image_excluded_from_figure_catalog(tmp_path: Path):
    """A standalone image whose folder resolves to `normative` (guia-folded,
    ADR-1) is excluded from the catalog entirely -- never appended, never
    copied (ADR-2)."""
    inbox = tmp_path / "inbox"
    (inbox / "guia").mkdir(parents=True)
    (inbox / "guia" / "diagrama.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections")

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"] == []


def test_standalone_evidence_role_image_kept_with_source_role_recorded(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "evidencia").mkdir(parents=True)
    (inbox / "evidencia" / "captura.png").write_bytes(_PIXEL_PNG)
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections")

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    figure = catalog["figures"][0]
    assert figure["origin_relative_path"] == "evidencia/captura.png"
    assert figure["source_role"] == "evidence"
    assert figure["origin_kind"] == "standalone"


def test_standalone_survivor_copied_to_stable_path_atomically_and_origin_rewritten(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "evidencia").mkdir(parents=True)
    (inbox / "evidencia" / "captura.PNG").write_bytes(_PIXEL_PNG)
    assets_dir = tmp_path / "assets"
    service = _service({})

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    sha8 = hashlib.sha256(_PIXEL_PNG).hexdigest()[:8]
    stable_name = f"fig-{sha8}.png"  # lower-cased origin suffix (ADR-3)
    stable_path = assets_dir / "figures" / stable_name
    assert stable_path.read_bytes() == _PIXEL_PNG
    # Atomic write (ADR-3): no leftover temp file after a clean run.
    assert list((assets_dir / "figures").glob(".asset-tmp-*")) == []

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    figure = catalog["figures"][0]
    assert figure["origin_relative_path"] == f"assets/figures/{stable_name}"
    assert figure["source_role"] == "evidence"


def test_vector_pdf_render_not_re_copied_by_standalone_copy_step(tmp_path: Path):
    """`origin_kind="pdf_render"` rows are already written by
    `_render_vector_pdf_figures` directly into `assets_dir/figures/` -- the
    standalone stable-path copy step (ADR-3) must skip them, never
    double-copy."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    assets_dir = tmp_path / "assets"
    service = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler()},
        image_metadata=_FakeImageMetadata(),
        pdf_render=_FakePdfRender(page_count=1),
    )

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    rendered = sorted(p.name for p in (assets_dir / "figures").iterdir())
    assert rendered == ["diagram-p01.png"]  # no duplicate `fig-<sha8>` copy
    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    figure = catalog["figures"][0]
    assert figure["origin_kind"] == "pdf_render"
    assert figure["origin_relative_path"] == "assets/figures/diagram-p01.png"


def test_sub_threshold_pdf_render_is_dropped_and_orphan_file_cleaned(tmp_path: Path):
    """A vector page render whose dimensions come back below
    MIN_FIGURE_DIMENSION_PX is dropped by the ADR-2 filter -- but the PNG was
    already written by render_pages before dims were known. It MUST be cleaned
    up, not left as an orphan under assets_dir/figures/ (ADR-2 invariant:
    dropped candidates are never copied/kept on disk; the standalone branch
    filters before copying, the pdf-render branch can only filter after)."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    assets_dir = tmp_path / "assets"
    service = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler()},
        image_metadata=_FakeSubThresholdImageMetadata(),
        pdf_render=_FakePdfRender(page_count=1),
    )

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"] == []  # sub-threshold render excluded from catalog
    figures_dir = assets_dir / "figures"
    leftover = sorted(p.name for p in figures_dir.iterdir()) if figures_dir.exists() else []
    assert leftover == []  # no orphan render file left behind


def test_parent_pdf_confirmed_role_propagates_to_vector_page_renders(tmp_path: Path):
    """ADR-1 divergence case: a PDF is a real classification-queue source,
    so its human-CONFIRMED role overrides raw `classify()` on every one of
    its page-render rows."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.pdf").write_bytes(b"vector-pdf-bytes")
    assets_dir = tmp_path / "assets"
    service = IngestService(
        _FakeDetector({"diagram.pdf": "pdf"}),
        {"pdf": _FakePdfHandler()},
        image_metadata=_FakeImageMetadata(),
        pdf_render=_FakePdfRender(page_count=1),
    )

    # First scan: no confirmed role yet -- raw classify("diagram.pdf") has no
    # folder/filename lexicon signal -> "unknown", kept (fail-open).
    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)
    first_catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert first_catalog["figures"][0]["source_role"] == "unknown"

    queue_path = inbox / "_classification-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["entries"]["diagram.pdf"]["confirmed_role"] = "normative"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    # Confirmed "normative" now wins over raw classify() -> dropped (ADR-2).
    second_catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert second_catalog["figures"] == []
