# tests/unit/infrastructure/test_source_type_detector.py
import sys
import zipfile
from pathlib import Path

from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter

_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n"


def _write_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")


def test_detects_pdf_by_magic_bytes(tmp_path: Path):
    path = tmp_path / "source.pdf"
    path.write_bytes(_PDF_BYTES)
    assert FiletypeDetectorAdapter().detect(path) == "pdf"


def test_detects_docx_by_magic_bytes(tmp_path: Path):
    path = tmp_path / "source.docx"
    _write_docx(path)
    assert FiletypeDetectorAdapter().detect(path) == "docx"


def test_detects_docx_by_magic_bytes_even_with_misleading_extension(tmp_path: Path):
    # Magic-byte detection must win over an unrelated/wrong extension.
    path = tmp_path / "source.bin"
    _write_docx(path)
    assert FiletypeDetectorAdapter().detect(path) == "docx"


def test_falls_back_to_extension_for_markdown(tmp_path: Path):
    path = tmp_path / "source.md"
    path.write_text("# no magic bytes here", encoding="utf-8")
    assert FiletypeDetectorAdapter().detect(path) == "md"


def test_falls_back_to_extension_for_txt(tmp_path: Path):
    path = tmp_path / "source.txt"
    path.write_text("plain text, no signature", encoding="utf-8")
    assert FiletypeDetectorAdapter().detect(path) == "txt"


def test_unknown_type_returns_empty_string(tmp_path: Path):
    path = tmp_path / "source.xyz"
    path.write_bytes(b"not a recognizable format at all")
    assert FiletypeDetectorAdapter().detect(path) == ""


def test_unknown_extension_with_no_magic_bytes_returns_empty_string_not_none(tmp_path: Path):
    path = tmp_path / "mystery"
    path.write_bytes(b"\x00\x01\x02 unrecognizable")
    result = FiletypeDetectorAdapter().detect(path)
    assert result == ""
    assert isinstance(result, str)


def test_missing_filetype_library_falls_back_to_extension_instead_of_raising(tmp_path: Path, monkeypatch):
    # The class contract is "never raises": a missing optional lib costs magic-byte sniffing only.
    monkeypatch.setitem(sys.modules, "filetype", None)  # makes `import filetype` raise ImportError
    md = tmp_path / "source.md"
    md.write_text("# hi", encoding="utf-8")
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(_PDF_BYTES)
    detector = FiletypeDetectorAdapter()
    assert detector.detect(md) == "md"
    assert detector.detect(pdf) == ""
