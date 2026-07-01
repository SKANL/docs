from __future__ import annotations

from pathlib import Path

import pytest

from docs.domain.qa import ensure_child_path, render_qa_report
from docs.domain.review import Issue, ReviewResult


def test_ensure_child_path_accepts_a_real_child(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    ensure_child_path(parent, child)  # must not raise


def test_ensure_child_path_rejects_identical_paths(tmp_path):
    parent = tmp_path / "same"
    parent.mkdir()
    with pytest.raises(RuntimeError, match="Ruta insegura"):
        ensure_child_path(parent, parent)


def test_ensure_child_path_rejects_a_non_child_path(tmp_path):
    parent = tmp_path / "parent"
    other = tmp_path / "other"
    parent.mkdir()
    other.mkdir()
    with pytest.raises(RuntimeError, match="Ruta insegura"):
        ensure_child_path(parent, other)


def test_render_qa_report_includes_pdf_size_and_png_count(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert f"- PDF: {pdf_path} ({pdf_path.stat().st_size} bytes)" in report
    assert "- PNG pages: 0" in report


def test_render_qa_report_reports_missing_pdf_as_zero_bytes(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "missing.pdf"
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert f"- PDF: {pdf_path} (0 bytes)" in report


def test_render_qa_report_embeds_format_audit_markdown(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    audit = ReviewResult([Issue("error", "Margen incorrecto")])
    report = render_qa_report(docx_path, pdf_path, [], audit)
    assert audit.to_markdown() in report


def test_render_qa_report_lists_document_audits_with_ok_and_fail_markers(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    document_audits = [
        {"name": "heading_audit.py", "ok": True, "report": "out/heading.txt"},
        {"name": "section_audit.py", "ok": False, "report": "out/section.txt"},
    ]
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult(), document_audits)
    assert "- OK `heading_audit.py`: out/heading.txt" in report
    assert "- FAIL `section_audit.py`: out/section.txt" in report


def test_render_qa_report_notes_no_document_audits_when_list_is_empty(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult(), [])
    assert "- No ejecutadas." in report


def test_render_qa_report_includes_manual_checklist_items(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert "- [ ] Sin texto cortado o solapado." in report
    assert "- [ ] Figuras con caption inferior." in report
