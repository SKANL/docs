# tests/integration/test_opendataloader_pdf_adapter.py
"""`SourceIngestPort` implementation for PDF sources via `opendataloader-pdf`
(document-ingest spec: `Type-Based Ingest Routing` scenario "PDF routed to
opendataloader-pdf", `Tool-Failure Reporting` scenario "opendataloader-pdf
conversion failure"). Binding conditions from the 5.1 spike / PR5
fresh-review round 2, carried into PR6 task 6.3:

(a) temp-then-atomic-rename — a failing conversion must leave no partial
    file at the deterministic final path;
(b) a kind already resolved by the detector ("pdf") must survive into the
    `status: "error"` report entry;
(c) resolve Java via the `ToolResolverPort` pattern, clear error when
    absent, skip real-tool integration tests when unavailable;
(d) each `opendataloader_pdf.convert()` call spawns a JVM, so all PDFs
    pending conversion in one inbox scan must be batched into ONE call;
(e) hybrid AI/OCR backends must stay off (local-only, deterministic).
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any

import pytest

from docs.infrastructure.ingest.opendataloader_pdf_adapter import OpendataloaderPdfAdapter
from docs.infrastructure.tools.java_resolution import resolve_java_executable

_HAS_JAVA = shutil.which("java") is not None
_HAS_PILLOW = True
try:
    from PIL import Image
except ImportError:  # pragma: no cover - environment-dependent
    _HAS_PILLOW = False


class _FakeToolResolver:
    def __init__(self, java_path: str | None) -> None:
        self.java_path = java_path

    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None:
        return None

    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None:
        return None

    def resolve_java(self, paths: dict[str, Any]) -> str | None:
        return self.java_path


def _minimal_pdf(text: str) -> bytes:
    """Hand-built minimal valid single-page PDF (no external PDF-writer lib
    is installed in this environment) — enough for opendataloader-pdf's Java
    pipeline to parse and convert to Markdown."""
    stream_body = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream_body)).encode() + b" >>\nstream\n" + stream_body + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return bytes(out)


def _write_pdf(path: Path, text: str) -> Path:
    path.write_bytes(_minimal_pdf(text))
    return path


def _minimal_pdf_with_raster_image(text: str, jpeg_bytes: bytes, w: int = 40, h: int = 40) -> bytes:
    """Same hand-built minimal PDF as `_minimal_pdf`, plus a single embedded
    raster (DCTDecode/JPEG) Image XObject painted on the page -- lets a real
    opendataloader-pdf run exercise external raster extraction without
    needing an external PDF-writer library."""
    stream_body = (
        f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET q {w} 0 0 {h} 100 400 cm /Im1 Do Q".encode("latin-1")
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream_body)).encode() + b" >>\nstream\n" + stream_body + b"\nendstream",
        (
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(w).encode()
            + b" /Height "
            + str(h).encode()
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
            + str(len(jpeg_bytes)).encode()
            + b" >>\nstream\n"
            + jpeg_bytes
            + b"\nendstream"
        ),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return bytes(out)


def _write_pdf_with_raster_image(path: Path, text: str) -> Path:
    img = Image.new("RGB", (40, 40), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    path.write_bytes(_minimal_pdf_with_raster_image(text, buf.getvalue()))
    return path


def test_resolve_java_executable_finds_real_java_on_path():
    assert (resolve_java_executable({}) is not None) == _HAS_JAVA


def test_resolve_java_executable_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_java_executable({}) is None


def test_resolve_java_executable_uses_configured_bin_when_which_misses(monkeypatch, tmp_path):
    fake_java = tmp_path / "java.exe"
    fake_java.write_text("not real")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_java_executable({"java_bin": str(fake_java)}) == str(fake_java)


def test_missing_java_reports_clear_error_and_leaves_no_partial_output(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf(inbox / "doc.pdf", "Hello")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(None))

    with pytest.raises(RuntimeError, match=r"[Jj]ava"):
        adapter.ingest(src, out_dir, "pdf")

    assert list(out_dir.iterdir()) == []


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_pdf_source_produces_markdown(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf(inbox / "report.pdf", "Hello Ingest Test")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    output = adapter.ingest(src, out_dir, "pdf")

    assert output.exists()
    assert output.parent == out_dir
    assert output.name.startswith("report-pdf-")
    assert "Hello Ingest Test" in output.read_text(encoding="utf-8")


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_output_naming_uses_passed_kind_not_source_extension(tmp_path: Path):
    # FRESH-REVIEW FINDING 1 unit-level check: a source with a misleading
    # extension (here `.txt` on a real PDF) must still be named using the
    # `kind` IngestService passes in, not any suffix derived from the file
    # itself.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf(inbox / "paper.txt", "Mismatched Extension")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    output = adapter.ingest(src, out_dir, "pdf")

    assert output.name.startswith("paper-pdf-")
    assert "Mismatched Extension" in output.read_text(encoding="utf-8")


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_batches_all_pending_pdfs_in_one_convert_call(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src_a = _write_pdf(inbox / "a.pdf", "Doc A")
    src_b = _write_pdf(inbox / "b.pdf", "Doc B")
    src_c = _write_pdf(inbox / "c.pdf", "Doc C")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    import docs.infrastructure.ingest.opendataloader_pdf_adapter as mod

    real_convert = mod.opendataloader_pdf.convert
    calls: list[list[str]] = []

    def _spy_convert(input_path, **kwargs):
        calls.append(list(input_path) if isinstance(input_path, list) else [input_path])
        return real_convert(input_path, **kwargs)

    monkeypatch.setattr(mod.opendataloader_pdf, "convert", _spy_convert)

    output_a = adapter.ingest(src_a, out_dir, "pdf")
    output_b = adapter.ingest(src_b, out_dir, "pdf")
    output_c = adapter.ingest(src_c, out_dir, "pdf")

    assert len(calls) == 1, "all three pending PDFs must be converted in a single convert() call"
    assert len(calls[0]) == 3
    assert output_a.exists() and output_b.exists() and output_c.exists()


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_one_corrupt_pdf_in_a_batch_does_not_abort_its_siblings(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    good = _write_pdf(inbox / "good.pdf", "Good Doc")
    bad = inbox / "bad.pdf"
    bad.write_text("not a real pdf")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    good_output = adapter.ingest(good, out_dir, "pdf")
    assert good_output.exists()
    assert "Good Doc" in good_output.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"bad\.pdf"):
        adapter.ingest(bad, out_dir, "pdf")

    # the failed file must leave no partial output anywhere under out_dir
    assert not any(p.stem.startswith("bad-pdf-") for p in out_dir.iterdir())


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_conversion_failure_leaves_no_partial_output_for_failed_file(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    bad = inbox / "onlybad.pdf"
    bad.write_text("not a real pdf")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    with pytest.raises(RuntimeError):
        adapter.ingest(bad, out_dir, "pdf")

    assert list(out_dir.iterdir()) == []


# --- Refinement: extract embedded raster so page-render targets only
# genuinely vector-only PDFs (the `_media/` gate `_render_vector_pdf_figures`
# checks was always empty because `image_output` was hardcoded to "off") ---


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_requests_external_raster_image_extraction(tmp_path: Path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf(inbox / "report.pdf", "Hello")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    import docs.infrastructure.ingest.opendataloader_pdf_adapter as mod

    real_convert = mod.opendataloader_pdf.convert
    calls: list[dict[str, Any]] = []

    def _spy_convert(input_path, **kwargs):
        calls.append(kwargs)
        return real_convert(input_path, **kwargs)

    monkeypatch.setattr(mod.opendataloader_pdf, "convert", _spy_convert)

    adapter.ingest(src, out_dir, "pdf")

    assert len(calls) == 1
    assert calls[0]["image_output"] == "external"
    assert calls[0]["image_format"] == "png"


@pytest.mark.skipif(not _HAS_JAVA or not _HAS_PILLOW, reason="Java or Pillow not installed")
def test_pdf_with_embedded_raster_populates_content_addressed_media_dir(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf_with_raster_image(inbox / "withimg.pdf", "Hello Image Test")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    output = adapter.ingest(src, out_dir, "pdf")

    media_dir = output.with_name(f"{output.stem}_media")
    assert media_dir.is_dir()
    extracted = list(media_dir.iterdir())
    assert len(extracted) == 1
    assert extracted[0].suffix == ".png"
    assert extracted[0].stat().st_size > 0


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_vector_only_pdf_leaves_no_media_dir(tmp_path: Path):
    # No embedded raster -- the paired `_media/` dir must stay absent so the
    # downstream page-render gate (`_render_vector_pdf_figures`) still fires
    # for this genuinely vector-only PDF.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _write_pdf(inbox / "vectoronly.pdf", "No Images Here")
    out_dir = tmp_path / "ingested"
    out_dir.mkdir()
    adapter = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java")))

    output = adapter.ingest(src, out_dir, "pdf")

    media_dir = output.with_name(f"{output.stem}_media")
    assert not media_dir.exists()


@pytest.mark.skipif(not _HAS_JAVA or not _HAS_PILLOW, reason="Java or Pillow not installed")
def test_extracted_media_is_byte_identical_across_runs(tmp_path: Path):
    inbox_1 = tmp_path / "inbox1"
    inbox_1.mkdir()
    src_1 = _write_pdf_with_raster_image(inbox_1 / "withimg.pdf", "Hello Image Test")
    out_dir_1 = tmp_path / "ingested1"
    out_dir_1.mkdir()
    output_1 = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java"))).ingest(
        src_1, out_dir_1, "pdf"
    )
    media_1 = output_1.with_name(f"{output_1.stem}_media")
    image_1 = next(media_1.iterdir()).read_bytes()

    inbox_2 = tmp_path / "inbox2"
    inbox_2.mkdir()
    src_2 = _write_pdf_with_raster_image(inbox_2 / "withimg.pdf", "Hello Image Test")
    out_dir_2 = tmp_path / "ingested2"
    out_dir_2.mkdir()
    output_2 = OpendataloaderPdfAdapter(_FakeToolResolver(shutil.which("java"))).ingest(
        src_2, out_dir_2, "pdf"
    )
    media_2 = output_2.with_name(f"{output_2.stem}_media")
    image_2 = next(media_2.iterdir()).read_bytes()

    assert image_1 == image_2
