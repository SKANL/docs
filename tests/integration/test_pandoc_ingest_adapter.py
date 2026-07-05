# tests/integration/test_pandoc_ingest_adapter.py
"""`SourceIngestPort` implementation for docx/odt (document-ingest spec:
`Type-Based Ingest Routing` scenario "DOCX/ODT routed to pandoc with media
extraction", `Tool-Failure Reporting` scenario "Missing pandoc executable").
"""
from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from docs.application.ingest import IngestService
from docs.domain.ingest_naming import sha256_hex
from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
from docs.infrastructure.ingest.pandoc_ingest_adapter import PandocIngestAdapter

_HAS_PANDOC = shutil.which("pandoc") is not None

# 1x1 red-pixel PNG (raw bytes) — small enough to embed inline, real enough
# for pandoc to recognize and extract as media.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


class _FakeToolResolver:
    def __init__(self, pandoc_path: str | None) -> None:
        self.pandoc_path = pandoc_path

    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None:
        return self.pandoc_path

    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None:
        return None


def _docx_with_image(tmp_path: Path, name: str) -> Path:
    pixel = tmp_path / "pixel.png"
    pixel.write_bytes(_PIXEL_PNG)
    seed = tmp_path / f"_seed_{name}.md"
    seed.write_text("# Title\n\nSome text.\n\n![alt](pixel.png)\n", encoding="utf-8")
    target = tmp_path / name
    subprocess.run(
        [shutil.which("pandoc"), seed.name, "-o", str(target)], cwd=tmp_path, check=True
    )
    return target


def _odt_source(tmp_path: Path, name: str) -> Path:
    seed = tmp_path / f"_seed_{name}.md"
    seed.write_text("# Title\n\nPlain ODT text.\n", encoding="utf-8")
    target = tmp_path / name
    subprocess.run([shutil.which("pandoc"), str(seed), "-o", str(target)], check=True)
    return target


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_docx_with_image_produces_markdown_and_media_dir(tmp_path: Path):
    src = _docx_with_image(tmp_path, "report.docx")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = PandocIngestAdapter(_FakeToolResolver(shutil.which("pandoc")))

    output = adapter.ingest(src, out_dir, "docx")

    assert output.exists()
    assert output.parent == out_dir
    assert output.name.startswith("report-docx-")
    assert output.name.endswith(".md")
    media_dir = out_dir / (output.stem + "_media")
    assert media_dir.is_dir()
    assert any(media_dir.rglob("*.png"))
    text = output.read_text(encoding="utf-8")
    assert "Title" in text


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_odt_source_produces_markdown(tmp_path: Path):
    src = _odt_source(tmp_path, "report.odt")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = PandocIngestAdapter(_FakeToolResolver(shutil.which("pandoc")))

    output = adapter.ingest(src, out_dir, "odt")

    assert output.exists()
    assert output.name.startswith("report-odt-")
    assert "Title" in output.read_text(encoding="utf-8")


def test_missing_pandoc_reports_clear_error_and_leaves_no_partial_output(tmp_path: Path):
    src = tmp_path / "report.docx"
    src.write_bytes(b"not a real docx, but pandoc is unavailable anyway")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = PandocIngestAdapter(_FakeToolResolver(None))

    with pytest.raises(RuntimeError, match="[Pp]andoc"):
        adapter.ingest(src, out_dir, "docx")

    assert list(out_dir.iterdir()) == []


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_conversion_failure_leaves_no_partial_output(tmp_path: Path):
    # A source with a `.docx` name but corrupt/non-docx bytes makes pandoc
    # itself fail (CalledProcessError) — the adapter must not leave any
    # partial file at the deterministic final path (fresh-review carry-
    # forward (a)).
    src = tmp_path / "corrupt.docx"
    src.write_bytes(b"this is not a valid docx zip archive")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = PandocIngestAdapter(_FakeToolResolver(shutil.which("pandoc")))

    with pytest.raises(subprocess.CalledProcessError):
        adapter.ingest(src, out_dir, "docx")

    assert list(out_dir.iterdir()) == []


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_misleading_extension_docx_is_ingested_via_detected_kind_not_suffix(tmp_path: Path):
    # FRESH-REVIEW FINDING 1 repro: a real DOCX saved with a `.doc` name is
    # still detected as "docx" by `FiletypeDetectorAdapter`'s magic-byte
    # sniffing and routed to this adapter by `IngestService`. Before the fix,
    # the adapter re-derived `kind` from `src.suffix` ("doc") instead of using
    # the kind the router already resolved, so it passed the file to pandoc
    # with no explicit reader — pandoc then inferred the format from the
    # `.doc` extension and failed (exit 21, "Unknown input format doc").
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    # Build a REAL docx first (pandoc only accepts a `.docx` output extension
    # when producing one), then rename it with a misleading `.doc` extension
    # — the bytes are genuinely docx, only the filename lies.
    built = _docx_with_image(build_dir, "report.docx")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = inbox / "report.doc"
    shutil.copy(built, src)
    sections_dir = tmp_path / "sections"
    adapter = PandocIngestAdapter(_FakeToolResolver(shutil.which("pandoc")))
    service = IngestService(FiletypeDetectorAdapter(), {"docx": adapter, "odt": adapter})

    first = service.ingest_inbox(inbox, sections_dir)

    entry = first["files"][0]
    assert entry["kind"] == "docx"
    assert entry["status"] == "ingested"
    output_path = Path(entry["output"])
    assert output_path.name.startswith("report-docx-")
    assert output_path.name.endswith(".md")

    second = service.ingest_inbox(inbox, sections_dir)
    assert second["files"][0]["status"] == "skipped"
    assert second["files"][0]["output"] == entry["output"]


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_retry_after_orphaned_media_dir_converges_to_complete_output(tmp_path: Path):
    # FRESH-REVIEW FINDING 2 repro: the adapter finalizes the media dir, THEN
    # the `.md` file, as two separate `os.replace` calls. If a prior attempt
    # died between those two steps, it leaves the media dir in place with no
    # paired `.md` — `IngestService`'s skip-check only looks at the `.md`, so
    # a retry re-runs pandoc and, before the fix, `atomic_finalize` tries to
    # `os.replace` the fresh media dir onto that stale non-empty directory
    # and raises instead of converging.
    src = _docx_with_image(tmp_path, "report.docx")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = PandocIngestAdapter(_FakeToolResolver(shutil.which("pandoc")))

    sha8 = sha256_hex(src.read_bytes())[:8]
    stem_tag = f"report-docx-{sha8}"
    stale_media_dir = out_dir / f"{stem_tag}_media"
    stale_media_dir.mkdir()
    (stale_media_dir / "stale-leftover.bin").write_bytes(b"orphaned from a failed prior attempt")
    assert not (out_dir / f"{stem_tag}.md").exists()

    output = adapter.ingest(src, out_dir, "docx")

    assert output.exists()
    assert output.name == f"{stem_tag}.md"
    media_dir = out_dir / f"{stem_tag}_media"
    assert media_dir.is_dir()
    assert any(media_dir.rglob("*.png")), "media dir must contain the real converted asset, not the stale leftover"
    assert not (media_dir / "stale-leftover.bin").exists(), "stale orphaned file must not survive the retry"
