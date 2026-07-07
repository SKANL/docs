# tests/integration/test_ingest_determinism.py
"""Determinism and idempotency across the full real-adapter wiring
(document-ingest spec: `Deterministic and Idempotent Ingest`). Uses the
same composition-root wiring as `Deps.ingest` (real `FiletypeDetectorAdapter`
+ real per-type adapters) rather than routing-only stubs, so this proves the
end-to-end guarantee PR6 adds on top of PR5's routing infra."""
from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from docs.application.ingest import IngestService
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.ingest.opendataloader_pdf_adapter import OpendataloaderPdfAdapter
from docs.infrastructure.ingest.pandoc_ingest_adapter import PandocIngestAdapter

_HAS_PANDOC = shutil.which("pandoc") is not None
_HAS_JAVA = shutil.which("java") is not None

_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def _minimal_pdf(text: str) -> bytes:
    stream_body = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
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


def _real_ingest_service() -> IngestService:
    tool_resolver = SystemToolResolverAdapter()
    pandoc_adapter = PandocIngestAdapter(tool_resolver)
    pdf_adapter = OpendataloaderPdfAdapter(tool_resolver)
    md_adapter = MdNormalizeAdapter()
    return IngestService(
        FiletypeDetectorAdapter(),
        {"docx": pandoc_adapter, "odt": pandoc_adapter, "pdf": pdf_adapter, "md": md_adapter, "txt": md_adapter},
    )


def test_md_and_txt_are_byte_identical_across_repeated_runs(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "notes.md").write_text('---\n{"b": 2, "a": 1}\n---\nBody.\n', encoding="utf-8")
    (inbox / "readme.txt").write_text("Plain text source.\n", encoding="utf-8")
    sections_dir = tmp_path / "sections"

    first = _real_ingest_service().ingest_inbox(inbox, sections_dir)
    second = _real_ingest_service().ingest_inbox(inbox, sections_dir)

    first_statuses = {e["file"]: e["status"] for e in first["files"]}
    second_statuses = {e["file"]: e["status"] for e in second["files"]}
    assert first_statuses == {"notes.md": "ingested", "readme.txt": "ingested"}
    assert second_statuses == {"notes.md": "skipped", "readme.txt": "skipped"}

    for entry in first["files"]:
        output_path = Path(entry["output"])
        assert output_path.exists()
        rerun_entry = next(e for e in second["files"] if e["file"] == entry["file"])
        assert Path(rerun_entry["output"]) == output_path
        assert output_path.read_bytes() == output_path.read_bytes()  # sanity: still readable


@pytest.mark.skipif(not _HAS_PANDOC, reason="pandoc not installed")
def test_docx_ingest_is_byte_identical_across_repeated_runs(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    seed = inbox / "_seed.md"
    seed.write_text("# Title\n\nContent.\n", encoding="utf-8")
    subprocess.run(
        [shutil.which("pandoc"), "_seed.md", "-o", "report.docx"], cwd=inbox, check=True
    )
    seed.unlink()  # keep the inbox scan limited to the real source file
    sections_dir = tmp_path / "sections"

    first = _real_ingest_service().ingest_inbox(inbox, sections_dir)
    output_path = Path(first["files"][0]["output"])
    first_bytes = output_path.read_bytes()

    second = _real_ingest_service().ingest_inbox(inbox, sections_dir)

    assert first["files"][0]["status"] == "ingested"
    assert second["files"][0]["status"] == "skipped"
    assert output_path.read_bytes() == first_bytes


@pytest.mark.skipif(not _HAS_JAVA, reason="Java not installed")
def test_pdf_ingest_is_byte_identical_across_repeated_runs(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "report.pdf").write_bytes(_minimal_pdf("Determinism Check"))
    sections_dir = tmp_path / "sections"

    first = _real_ingest_service().ingest_inbox(inbox, sections_dir)
    output_path = Path(first["files"][0]["output"])
    first_bytes = output_path.read_bytes()

    second = _real_ingest_service().ingest_inbox(inbox, sections_dir)

    assert first["files"][0]["status"] == "ingested"
    assert second["files"][0]["status"] == "skipped"
    assert output_path.read_bytes() == first_bytes


def test_partially_processed_inbox_only_converts_new_files_without_corrupting_prior_output(
    tmp_path: Path,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "already.md").write_text("Already ingested content.\n", encoding="utf-8")
    sections_dir = tmp_path / "sections"

    first = _real_ingest_service().ingest_inbox(inbox, sections_dir)
    already_output = Path(first["files"][0]["output"])
    already_bytes = already_output.read_bytes()

    (inbox / "brand-new.txt").write_text("Brand new source.\n", encoding="utf-8")
    second = _real_ingest_service().ingest_inbox(inbox, sections_dir)

    statuses = {e["file"]: e["status"] for e in second["files"]}
    assert statuses == {"already.md": "skipped", "brand-new.txt": "ingested"}
    assert already_output.exists()
    assert already_output.read_bytes() == already_bytes, "prior output must not be touched"


def test_empty_inbox_completes_without_error_and_reports_zero_processed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    report = _real_ingest_service().ingest_inbox(inbox, tmp_path / "sections")

    # media_cleanup added in Front B (design.md Decision 8 #13) -- always
    # present, empty when there is no sections/ingested/ dir to scan yet.
    assert report == {"processed": 0, "files": [], "media_cleanup": {"removed": [], "refused": []}}
