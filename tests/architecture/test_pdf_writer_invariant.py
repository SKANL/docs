# tests/architecture/test_pdf_writer_invariant.py
"""Every PDF writer must end in `normalize_pdf_id`.

PDFium stamps a RANDOM `/ID` into the trailer on every save, so two runs over
identical input differ in exactly those bytes and nowhere else -- measured on
this repo: same 1758-byte output, first difference at offset 1662, only the
trailer `/ID` array. A writer that skips the normalizer therefore produces
non-deterministic output, which reads as a flaky byte-identity test and IS a
product bug.

This is the same shape as `test_docx_writer_invariant.py`, for the same
reason: the failure mode that actually happens is a new module that never
heard of the rule. An AST scan catches that, needs no GitNexus index, and
therefore never skips.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
NORMALIZER = "normalize_pdf_id"

# The normalizer's own home: it IS the fix, so it cannot be required to call
# itself. Named rather than pattern-matched, so a second exemption has to be
# argued for in a diff.
EXEMPT = {"domain/pdf_id.py"}


def _saves_a_pdf(tree: ast.AST, source: str) -> bool:
    """A `.save(...)` call in a module that actually deals with PDFium.

    The `pypdfium2` gate matters: `pdfium2_pdf_render_adapter` also calls
    `img.save(dest)` on a PIL image, but that writes a PNG. It is caught by
    this gate and cleared by the read-only check below -- it never opens a
    document for writing.
    """
    if "pypdfium2" not in source:
        return False
    return any(
        isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".save")
        for node in ast.walk(tree)
    )


def _writes_pdf_bytes(source: str) -> bool:
    """Distinguish a real PDF writer from a module that only READS PDFs.

    A PDF writer necessarily mutates page objects or saves a document; a
    renderer only rasterizes. Without this, the rasterizer's `img.save(...)`
    would be demanded to normalize a PDF `/ID` it never writes.
    """
    return any(
        marker in source
        for marker in ("FPDFPage_InsertObject", "FPDFPage_GenerateContent", "FPDF_SaveAsCopy")
    )


def _pdf_writers() -> dict[str, bool]:
    """{relative path: mentions the normalizer} for every PDF writer found."""
    writers: dict[str, bool] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT).as_posix()
        if relative in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        if not _saves_a_pdf(ast.parse(source), source) or not _writes_pdf_bytes(source):
            continue
        writers[relative] = NORMALIZER in source
    return writers


def test_the_scan_finds_at_least_one_pdf_writer():
    """Probe against a vacuous pass.

    An AST scan that silently stops matching reports "0 violations" forever,
    which is indistinguishable from a clean repo. If this fails, the scan is
    broken -- not the codebase.
    """
    assert _pdf_writers(), "the PDF-writer scan matched nothing; the scan itself is broken"


def test_every_pdf_writer_routes_through_the_id_normalizer():
    offenders = sorted(path for path, normalized in _pdf_writers().items() if not normalized)
    assert not offenders, (
        f"these modules save a PDF without {NORMALIZER}: {offenders}. "
        "PDFium writes a random trailer /ID on save, so skipping the "
        "normalizer makes the output non-deterministic."
    )


def test_the_rasterizer_is_not_mistaken_for_a_writer():
    """`pdfium2_pdf_render_adapter` saves PNGs, not PDFs. Demanding the PDF
    normalizer there would be a false positive that teaches people to widen
    `EXEMPT` -- which is how an invariant test stops meaning anything."""
    assert "infrastructure/pdf/pdfium2_pdf_render_adapter.py" not in _pdf_writers()
