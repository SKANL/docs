# tests/integration/test_qa_service.py
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from docx import Document

from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter

_HAS_LIBREOFFICE = shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _make_service() -> QaService:
    return QaService(LibreOfficeQaAdapter(), FormatAuditService(PythonDocxAuditAdapter()))


def _make_docx(tmp_path: Path) -> Path:
    path = tmp_path / "doc.docx"
    Document().save(path)
    return path


def test_qa_docx_raises_when_docx_missing(tmp_path):
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}
    with pytest.raises(FileNotFoundError, match="No existe DOCX para QA"):
        service.qa_docx(config, tmp_path / "missing.docx")


@pytest.mark.skipif(_HAS_LIBREOFFICE, reason="requires LibreOffice to be unavailable")
def test_qa_docx_strict_raises_when_libreoffice_unavailable(tmp_path):
    # render_docx_to_pdf runs first (Design Decision 6: render-before-guard
    # order matches legacy), so without LibreOffice it raises its own
    # RuntimeError before the code ever reaches the PNG guard.
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    with pytest.raises(RuntimeError):
        service.qa_docx(config, docx_path, strict=True)


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_strict_always_raises_since_png_rendering_is_out_of_scope(tmp_path):
    # Only reachable when render_docx_to_pdf succeeds, i.e. LibreOffice is
    # installed: the PNG-per-page guard still always raises in strict mode.
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    with pytest.raises(RuntimeError, match="QA estricto requiere PNG por página"):
        service.qa_docx(config, docx_path, strict=True)


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_non_strict_writes_report_and_returns_output_dir(tmp_path):
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    output_dir = service.qa_docx(config, docx_path, strict=False)

    assert output_dir == tmp_path / "qa" / "doc"
    report_text = (output_dir / "qa-report.md").read_text(encoding="utf-8")
    assert "# QA DOCX" in report_text
    assert (output_dir / "doc.pdf").stat().st_size > 0


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_cleans_up_a_pre_existing_output_dir(tmp_path):
    docx_path = _make_docx(tmp_path)
    output_dir = tmp_path / "qa" / "doc"
    output_dir.mkdir(parents=True)
    stale_file = output_dir / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}
    service.qa_docx(config, docx_path, strict=False)

    assert not stale_file.exists()
    assert (output_dir / "qa-report.md").exists()


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_reports_configured_documents_audit_results(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "heading_audit.py").write_text("print('ok')\n", encoding="utf-8")
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {
        "paths": {
            "output_qa_dir": str(tmp_path / "qa"),
            "documents_scripts_dir": str(scripts_dir),
        }
    }

    output_dir = service.qa_docx(config, docx_path, strict=False)

    report_text = (output_dir / "qa-report.md").read_text(encoding="utf-8")
    assert "- OK `heading_audit.py`" in report_text
    assert "- OK `section_audit.py`" in report_text  # not found -> ok under non-strict
