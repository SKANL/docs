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

    output = adapter.ingest(src, out_dir)

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

    output = adapter.ingest(src, out_dir)

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
        adapter.ingest(src, out_dir)

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
        adapter.ingest(src, out_dir)

    assert list(out_dir.iterdir()) == []
