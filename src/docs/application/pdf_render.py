# src/docs/application/pdf_render.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.qa_render_port import QaRenderPort


class PdfRendererAdapter:
    """`DocumentRendererPort` implementation for PDF output (design.md item
    C-pdf): builds the DOCX draft first (reusing `DocxRendererAdapter`, or
    any `DocumentRendererPort` producing docx) then converts it via the
    already-wired `LibreOfficeQaAdapter.render_docx_to_pdf` soffice
    subprocess -- no new conversion path, no new toolchain.

    PDF output is an explicitly non-byte-deterministic derived artifact
    (soffice version affects rendering); unlike docx/HTML it is NOT held to
    the byte-identity guarantee (spec: document-pipeline "Reproducibility
    Boundary Principle" amendment). When the LibreOffice/soffice toolchain
    is absent, `build()` WARNs to stderr and returns `None` rather than
    raising -- the same best-effort degrade as `HtmlRendererAdapter` for
    pandoc, so a PDF-less environment never crashes the pipeline."""

    output_format = "pdf"

    def __init__(self, docx_renderer: DocumentRendererPort, qa_render: QaRenderPort) -> None:
        self.docx_renderer = docx_renderer
        self.qa_render = qa_render

    def stage_plan(self) -> list[tuple[str, bool]]:
        return [("build-pdf", True)]

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path | None:
        docx_path = self.docx_renderer.build(doc_id, config)
        output_dir = Path(config["paths"]["output_draft_dir"])
        try:
            pdf_path = self.qa_render.render_docx_to_pdf(config, docx_path, output_dir)
        except RuntimeError as exc:
            print(f"WARN: {exc} Se omite la salida PDF.", file=sys.stderr)
            return None
        if output is not None and Path(output) != pdf_path:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            pdf_path.replace(output)
            return Path(output)
        return pdf_path
