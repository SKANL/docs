from __future__ import annotations

from docx import Document
from docx.shared import Inches

from docs.application.structural_audit import StructuralAuditService
from docs.infrastructure.audit.structural_audit_adapter import StructuralAuditAdapter


def test_docx_structural_audit_checks_declarative_structure(tmp_path):
    docx_path = tmp_path / "report.docx"
    document = Document()
    document.core_properties.title = "Harness report"
    document.add_heading("INTRODUCTION", level=1)
    document.add_heading("METHODS", level=1)
    document.add_table(rows=1, cols=1)
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    document.save(docx_path)

    result = StructuralAuditService(StructuralAuditAdapter()).audit(
        docx_path,
        {
            "headings": ["INTRODUCTION", "METHODS"],
            "sections": ["INTRODUCTION", "METHODS"],
            "tables": {"minimum": 1},
            "images": {"minimum": 0},
            "captions": {"required": False},
            "references": {"required": False},
            "metadata": {"required": ["title"]},
            "page_size": (612, 792),
        },
    )

    assert result.passed is True
    assert result.issues == []


def test_docx_structural_audit_reports_missing_declared_requirements(tmp_path):
    docx_path = tmp_path / "report.docx"
    document = Document()
    document.add_heading("METHODS", level=1)
    document.save(docx_path)

    result = StructuralAuditService(StructuralAuditAdapter()).audit(
        docx_path,
        {
            "headings": ["INTRODUCTION"],
            "tables": {"minimum": 1},
            "references": {"required": True},
            "metadata": {"required": ["title"]},
        },
    )

    assert {issue.code for issue in result.issues} >= {
        "structure.headings.order",
        "structure.tables.minimum",
        "structure.references.missing",
        "structure.metadata.missing",
    }


def test_structural_audit_accepts_json_page_size_list(tmp_path):
    docx_path = tmp_path / "report.docx"
    document = Document()
    document.sections[0].page_width = Inches(8.5)
    document.sections[0].page_height = Inches(11)
    document.save(docx_path)

    result = StructuralAuditService(StructuralAuditAdapter()).audit(docx_path, {"page_size": [600, 790]})

    assert any(issue.code == "structure.page_size" for issue in result.issues)
