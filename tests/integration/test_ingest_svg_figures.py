# tests/integration/test_ingest_svg_figures.py
"""HIGH silent-failure fix: a standalone `.svg` dropped in `inbox/` used to
be undetectable by `FiletypeDetectorAdapter` (no magic bytes, no extension
fallback) and fell through to `sources` -> reported `status: "unsupported"`,
never reaching the figure catalog -- so it could never become an embeddable
`[[figure:label]]` figure. It is now a heuristic asset candidate (same as a
raster image), normalized + rasterized into a deterministic sibling
`<stem>.svg`/`<stem>.png` pair (mirrors
`generate_visuals.GenerateVisualsService._render_one`), and the PNG side is
cataloged. Uses a FAKE `SvgRasterizerPort` (writes a real, genuinely
parseable PNG) + the REAL `PythonDocxImageMetadataAdapter` -- hermetic, no
real resvg subprocess."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

from docs.application.ingest import IngestService
from docs.domain.svg_normalize import normalize_svg
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter

_RAW_SVG = '<svg xmlns="http://www.w3.org/2000/svg" id="abc"><rect width="10" height="10"/></svg>'


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def _solid_png(width: int, height: int) -> bytes:
    """A minimal, genuinely-parseable RGB PNG at the given size (mirrors
    `tests/integration/test_ingest_assets_figures.py`'s helper) -- real
    dimensions above `MIN_FIGURE_DIMENSION_PX` (100) so the mechanical
    size filter never masks the SVG-specific assertions these tests exist
    to check."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"".join(b"\x00" + bytes([180, 180, 180] * width) for _ in range(height))
    idat = zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


class _FakeDetector:
    """Mirrors the real `FiletypeDetectorAdapter`'s shape for this suite's
    fixtures: `.md`/`.txt` resolve via extension fallback, everything else
    (including a real SVG, which has no magic-byte signature and no text-
    extension fallback) returns "" -- so a test can prove the SVG never
    reaches `sources`/detection at all (it is excluded earlier, as a
    heuristic asset candidate)."""

    def detect(self, path: Path) -> str:
        if path.suffix.lower() in (".md", ".txt"):
            return path.suffix.lower().lstrip(".")
        return ""


class _TextEchoHandler:
    def ingest(self, src: Path, out_dir: Path, kind: str) -> Path:
        sha8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
        target = out_dir / f"{src.stem}-{kind}-{sha8}.md"
        target.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return target


class _FakeSvgRasterizer:
    """Deterministic fake `SvgRasterizerPort`: writes a real, parseable PNG
    derived only from `svg_path`'s content, so re-rasterizing the same
    normalized SVG always yields the same bytes (determinism contract)."""

    def __init__(self, size: tuple[int, int] = (150, 150), exc: Exception | None = None) -> None:
        self.size = size
        self.exc = exc
        self.calls: list[tuple[Path, Path]] = []

    def rasterize(self, svg_path: Path, png_path: Path) -> None:
        self.calls.append((svg_path, png_path))
        if self.exc is not None:
            raise self.exc
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(_solid_png(*self.size))


def _service(svg_rasterizer=None) -> IngestService:
    return IngestService(
        _FakeDetector(),
        {"md": _TextEchoHandler()},
        image_metadata=PythonDocxImageMetadataAdapter(),
        svg_rasterizer=svg_rasterizer,
    )


# --- standalone SVG becomes a cataloged, embeddable figure -----------------


def test_standalone_svg_is_rasterized_and_cataloged_as_figure(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.svg").write_text(_RAW_SVG, encoding="utf-8")
    assets_dir = tmp_path / "assets"
    rasterizer = _FakeSvgRasterizer(size=(150, 150))
    service = _service(svg_rasterizer=rasterizer)

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    # Never routed to markdown ingest / never "unsupported" -- excluded from
    # `sources` as a heuristic asset candidate, same as a raster image.
    assert all(e.get("file") != "diagram.svg" for e in report["files"])
    assert {"relative_path": "diagram.svg", "reason": "asset_candidate"} in report["ignored"]

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["figures"]) == 1
    figure = catalog["figures"][0]
    assert figure["origin_relative_path"].endswith(".png")
    assert figure["width_px"] == 150
    assert figure["height_px"] == 150
    assert figure["origin_kind"] == "standalone"

    # The `.svg` sibling stays on disk next to the PNG (same stem) -- this is
    # what makes it `[[figure:label]]`-bindable via the HTML sibling-swap
    # (`html_render._prefer_sibling_svg`) and DOCX assembly.
    png_path = assets_dir / Path(figure["origin_relative_path"]).relative_to("assets")
    svg_sibling = png_path.with_suffix(".svg")
    assert png_path.exists()
    assert svg_sibling.exists()
    assert svg_sibling.read_text(encoding="utf-8") == normalize_svg(_RAW_SVG)


# --- resvg/rasterizer absent -> WARN + skip, never crashes ingest ----------


def test_svg_rasterizer_absent_warns_and_skips_no_catalog_entry(tmp_path: Path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.svg").write_text(_RAW_SVG, encoding="utf-8")
    (inbox / "notes.md").write_text("# hello", encoding="utf-8")
    service = _service(svg_rasterizer=None)  # resvg unavailable

    report = service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=tmp_path / "assets")

    # Other sources still ingest -- one bad SVG never blocks the batch.
    assert any(e["file"] == "notes.md" and e["status"] == "ingested" for e in report["files"])

    catalog_path = tmp_path / "sections" / "figure-catalog.json"
    assert catalog_path.exists()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["figures"] == []  # no crash, but no entry either

    stderr = capsys.readouterr().err
    assert "WARN" in stderr
    assert "diagram.svg" in stderr


def test_svg_rasterize_exception_warns_and_skips_no_orphan_files(tmp_path: Path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "diagram.svg").write_text(_RAW_SVG, encoding="utf-8")
    assets_dir = tmp_path / "assets"
    rasterizer = _FakeSvgRasterizer(exc=RuntimeError("resvg no encontrado en PATH"))
    service = _service(svg_rasterizer=rasterizer)

    service.ingest_inbox(inbox, tmp_path / "sections", assets_dir=assets_dir)

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    assert catalog["figures"] == []
    figures_dir = assets_dir / "figures"
    leftover = sorted(p.name for p in figures_dir.iterdir()) if figures_dir.exists() else []
    assert leftover == []  # no orphan .svg left behind after a failed rasterize

    assert "WARN" in capsys.readouterr().err


# --- determinism: ingest the same SVG twice -> byte-identical catalog+PNG --


def test_determinism_same_svg_ingested_twice_is_byte_identical(tmp_path: Path):
    def _run(root: Path) -> tuple[bytes, bytes]:
        inbox = root / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "diagram.svg").write_text(_RAW_SVG, encoding="utf-8")
        assets_dir = root / "assets"
        service = _service(svg_rasterizer=_FakeSvgRasterizer(size=(150, 150)))
        service.ingest_inbox(inbox, root / "sections", assets_dir=assets_dir)
        catalog_bytes = (root / "sections" / "figure-catalog.json").read_bytes()
        svg_bytes = next((assets_dir / "figures").glob("*.svg")).read_bytes()
        return catalog_bytes, svg_bytes

    run1 = _run(tmp_path / "run1")
    run2 = _run(tmp_path / "run2")
    assert run1 == run2


# --- backward-compat: raster images still ingest exactly as before ---------


def test_raster_image_ingest_unaffected_by_svg_support(tmp_path: Path):
    inbox = tmp_path / "inbox"
    (inbox / "images").mkdir(parents=True)
    pixel_png = _solid_png(150, 150)
    (inbox / "images" / "page-001.png").write_bytes(pixel_png)
    service = _service(svg_rasterizer=_FakeSvgRasterizer())

    service.ingest_inbox(inbox, tmp_path / "sections")

    catalog = json.loads((tmp_path / "sections" / "figure-catalog.json").read_text(encoding="utf-8"))
    figure = catalog["figures"][0]
    assert figure["origin_relative_path"] == "images/page-001.png"
    assert figure["origin_kind"] == "standalone"
    assert figure["sha256"] == hashlib.sha256(pixel_png).hexdigest()
