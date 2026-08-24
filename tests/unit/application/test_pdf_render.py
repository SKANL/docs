# tests/unit/application/test_pdf_render.py
"""`PdfRendererAdapter` — `DocumentRendererPort` implementation for PDF
output (SDD change harness-generality-and-revision, item C-pdf, PR3).

PDF is an explicitly non-byte-deterministic derived artifact (rendered via
LibreOffice/soffice, output varies by toolchain version) -- there is
deliberately no determinism/golden-byte test here (spec: document-pipeline
"Reproducibility Boundary Principle" amendment). What IS tested: the docx
build + docx->pdf conversion wiring, and the WARN+skip degradation when the
LibreOffice toolchain is absent (the primary testable path in this
environment, since soffice isn't installed here)."""
from __future__ import annotations

from pathlib import Path

from docs.application.pdf_render import PdfRendererAdapter
from docs.domain.ports.document_renderer_port import DocumentRendererPort


class _FakeDocxRenderer:
    output_format = "docx"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[tuple[str, dict]] = []

    def stage_plan(self):
        return [("build-docx", True), ("format-audit-docx", True), ("qa-docx", True)]

    def build(self, doc_id, config, output=None):
        self.calls.append((doc_id, config))
        return self.path


class _FakeQaRender:
    def __init__(self, pdf_path: Path | None = None, raise_exc: Exception | None = None) -> None:
        self.pdf_path = pdf_path
        self.raise_exc = raise_exc
        self.calls: list[tuple[dict, Path, Path]] = []

    def render_docx_to_pdf(self, config, docx_path, output_dir):
        self.calls.append((config, docx_path, output_dir))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.pdf_path


# --- DocumentRendererPort contract ----------------------------------------------


def test_pdf_renderer_adapter_declares_pdf_output_format():
    service = PdfRendererAdapter(_FakeDocxRenderer(Path("x.docx")), _FakeQaRender())
    assert service.output_format == "pdf"


def test_pdf_renderer_adapter_satisfies_document_renderer_port():
    service: DocumentRendererPort = PdfRendererAdapter(_FakeDocxRenderer(Path("x.docx")), _FakeQaRender())
    assert service.output_format == "pdf"
    assert service.stage_plan() == [("build-pdf", True)]


def test_pdf_renderer_adapter_resolves_via_registry_by_format():
    from docs.cli._shared import resolve_renderer

    service = PdfRendererAdapter(_FakeDocxRenderer(Path("x.docx")), _FakeQaRender())
    registry = {"pdf": service}
    resolved = resolve_renderer(registry, "pdf")
    assert resolved is service


# --- build: docx built first, then converted to pdf ------------------------------


def test_build_builds_docx_then_converts_to_pdf(tmp_path):
    docx_path = tmp_path / "tesina-draft.docx"
    docx_path.write_bytes(b"fake docx")
    pdf_path = tmp_path / "tesina-draft.pdf"
    pdf_path.write_bytes(b"fake pdf")
    docx_renderer = _FakeDocxRenderer(docx_path)
    qa_render = _FakeQaRender(pdf_path=pdf_path)
    service = PdfRendererAdapter(docx_renderer, qa_render)
    config = {"paths": {"output_draft_dir": str(tmp_path)}}

    result = service.build("doc-1", config)

    assert result == pdf_path
    assert docx_renderer.calls == [("doc-1", config)]
    assert qa_render.calls == [(config, docx_path, tmp_path)]


# --- build: soffice/LibreOffice absent -> WARN + skip (never crash) --------------


def test_build_returns_none_and_warns_when_libreoffice_unavailable(tmp_path, capsys):
    docx_path = tmp_path / "tesina-draft.docx"
    docx_path.write_bytes(b"fake docx")
    docx_renderer = _FakeDocxRenderer(docx_path)
    qa_render = _FakeQaRender(
        raise_exc=RuntimeError("LibreOffice/soffice no está disponible en PATH. Instálalo para renderizar QA visual.")
    )
    service = PdfRendererAdapter(docx_renderer, qa_render)
    config = {"paths": {"output_draft_dir": str(tmp_path)}}

    result = service.build("doc-1", config)

    assert result is None
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "PDF" in captured.err


def test_build_returns_none_and_warns_when_the_docx_renderer_itself_skips(tmp_path, capsys):
    # `DocumentRendererPort.build` may legitimately return `None` (degraded,
    # already WARNed). PdfRendererAdapter composes ANY docx-producing
    # renderer through that port, so it must not hand a `None` to
    # `render_docx_to_pdf` -- which would surface as an opaque adapter-level
    # TypeError instead of the WARN+skip this class documents.
    class _SkippingDocxRenderer:
        output_format = "docx"

        def stage_plan(self):
            return [("build-docx", True)]

        def build(self, doc_id, config, output=None):
            return None

    qa_render = _FakeQaRender(pdf_path=tmp_path / "never.pdf")
    service = PdfRendererAdapter(_SkippingDocxRenderer(), qa_render)

    result = service.build("doc-1", {"paths": {"output_draft_dir": str(tmp_path)}})

    assert result is None
    assert qa_render.calls == [], "no debe intentar convertir un .docx inexistente"
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "PDF" in captured.err
