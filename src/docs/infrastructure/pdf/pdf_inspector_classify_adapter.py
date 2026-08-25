# src/docs/infrastructure/pdf/pdf_inspector_classify_adapter.py
"""PDF classification via `pdf-inspector` (Rust, MIT, PDFium-backed).

`pdf-inspector` cannot WRITE PDFs, so it is used only for what it is uniquely
good at: telling us what kind of document this is before anything tries to
translate it.

Two of its signals gate real behaviour rather than decorating a report:
`pdf_type` decides whether there is a text layer to translate at all, and
`pages_with_columns` marks the pages where the single-column block grouping in
`domain/block_grouping.py` is not to be trusted.
"""
from __future__ import annotations

from pathlib import Path

import pdf_inspector

from docs.domain.ports.pdf_classify_port import PdfClassification


class PdfInspectorClassifyAdapter:
    """`PdfClassifyPort` implementation."""

    def classify(self, pdf_path: Path) -> PdfClassification:
        result = pdf_inspector.process_pdf(str(pdf_path))
        return PdfClassification(
            pdf_type=str(result.pdf_type),
            page_count=int(result.page_count),
            pages_needing_ocr=list(result.pages_needing_ocr),
            pages_with_columns=list(result.pages_with_columns),
            has_encoding_issues=bool(result.has_encoding_issues),
        )
