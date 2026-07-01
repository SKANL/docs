# tests/integration/test_insert_toc_field.py
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import insert_toc_field

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_with_toc_placeholder(tmp_path: Path) -> Path:
    document = Document()
    document.add_paragraph("[[TOC]]")
    path = tmp_path / "fixture.docx"
    document.save(path)
    return path


def test_insert_toc_field_replaces_placeholder_with_toc_field(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    result = insert_toc_field(path)
    assert result is True

    reopened = Document(str(path))
    target = next(p for p in reopened.paragraphs if "TOC" in p._p.xml or "actualizara" in p.text)
    xml = target._p.xml
    assert 'w:fldCharType="begin"' in xml
    assert 'TOC \\o "1-3" \\h \\z \\u' in xml
    assert 'w:fldCharType="separate"' in xml
    assert 'w:fldCharType="end"' in xml


def test_insert_toc_field_sets_update_fields_on_open(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    insert_toc_field(path)

    with zipfile.ZipFile(path) as archive:
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
    assert 'w:val="true"' in settings_xml
    assert "updateFields" in settings_xml


def test_insert_toc_field_returns_false_and_leaves_file_untouched_when_placeholder_missing(tmp_path):
    document = Document()
    document.add_paragraph("No placeholder here.")
    path = tmp_path / "no_toc.docx"
    document.save(path)
    before = path.read_bytes()

    result = insert_toc_field(path)
    assert result is False
    assert path.read_bytes() == before


def test_insert_toc_field_honors_custom_levels_argument(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    insert_toc_field(path, levels="1-2")
    reopened = Document(str(path))
    xml = "".join(p._p.xml for p in reopened.paragraphs)
    assert 'TOC \\o "1-2"' in xml
