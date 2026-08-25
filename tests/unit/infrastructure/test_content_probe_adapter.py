# tests/unit/infrastructure/test_content_probe_adapter.py
from __future__ import annotations

from PIL import Image

from docs.domain.ports.content_probe_port import ContentSignals
from docs.infrastructure.ingest.content_probe_adapter import FilesystemContentProbeAdapter


def test_probe_returns_lowercase_extension_without_dot(tmp_path):
    path = tmp_path / "manual.PDF"
    path.write_bytes(b"stub")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="pdf")


def test_probe_returns_empty_extension_for_extensionless_file(tmp_path):
    path = tmp_path / "README"
    path.write_bytes(b"stub")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="")


class _BadPath:
    """Simulates a locale/platform read failure (design.md §4 "Content probe
    reads differ by platform/locale") -- any attribute access that would
    normally read path data raises, instead of returning a string."""

    @property
    def suffix(self) -> str:
        raise OSError("simulated platform/locale failure")


def test_probe_failure_returns_empty_signals_fail_open():
    result = FilesystemContentProbeAdapter().probe(_BadPath())  # type: ignore[arg-type]

    assert result == ContentSignals()


# --- 4.3/4.4: PDF title + heading extraction (item D, PR4) ---------------


def _make_titled_pdf(path, title: str) -> None:
    Image.new("RGB", (20, 20), (255, 255, 255)).save(path, title=title)


def test_probe_pdf_extracts_title_from_metadata(tmp_path):
    path = tmp_path / "9f3ac1.pdf"
    _make_titled_pdf(path, "Guía de Normas Internas")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result.extension == "pdf"
    assert result.pdf_title == "Guía de Normas Internas"


def test_probe_pdf_without_toc_yields_empty_headings(tmp_path):
    path = tmp_path / "plain.pdf"
    _make_titled_pdf(path, "")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result.first_headings == ()


def test_probe_pdf_extracts_headings_from_table_of_contents(tmp_path, monkeypatch):
    path = tmp_path / "with-toc.pdf"
    _make_titled_pdf(path, "Manual")

    class _FakeBookmark:
        def __init__(self, title: str) -> None:
            self._title = title

        def get_title(self) -> str:
            return self._title

    fake_bookmarks = [_FakeBookmark("Introducción"), _FakeBookmark("Alcance"), _FakeBookmark("")]

    import docs.infrastructure.ingest.content_probe_adapter as adapter_module

    real_pdf_document = adapter_module.pdfium.PdfDocument

    class _FakeDocument:
        def __init__(self, path_str: str) -> None:
            self._real = real_pdf_document(path_str)

        def get_metadata_value(self, key: str) -> str:
            return self._real.get_metadata_value(key)

        def get_toc(self):
            return iter(fake_bookmarks)

        def close(self) -> None:
            self._real.close()

    monkeypatch.setattr(adapter_module.pdfium, "PdfDocument", _FakeDocument)

    result = FilesystemContentProbeAdapter().probe(path)

    assert result.first_headings == ("Introducción", "Alcance")


def test_probe_pdf_malformed_file_fails_open_on_all_fields(tmp_path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a real pdf")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="pdf")


# --- 4.3/4.4: first-N-bytes keyword scan for text/markdown ---------------


def test_probe_text_file_extracts_case_folded_sorted_keywords(tmp_path):
    path = tmp_path / "notas.md"
    path.write_text("Ficha de la Empresa: revisar Referencia y Ejemplo.", encoding="utf-8")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result.extension == "md"
    assert result.head_keywords == tuple(sorted(result.head_keywords))
    assert "ficha" in result.head_keywords
    assert "empresa" in result.head_keywords
    assert "Ficha" not in result.head_keywords


def test_probe_text_file_only_scans_head_bytes(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x " * 5000 + "solocola", encoding="utf-8")

    result = FilesystemContentProbeAdapter().probe(path)

    assert "solocola" not in result.head_keywords


def test_probe_non_pdf_non_text_extension_leaves_content_fields_empty(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\r\n")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="png")


# --- "found" is not "usable", the fourth time ---------------------------------


def test_a_text_file_renamed_to_docx_is_reported_as_an_unreadable_container(tmp_path):
    # Fourth appearance of one bug class in this repo: `safe_style_name` asked
    # whether a style was LISTED, `MermaidSvgRenderer` whether the binary was
    # PRESENT, `doctor` whether a toolchain was ON PATH -- and here, whether a
    # file EXISTS. Existing is not being a `.docx`: `doctor` reported
    # `template_docx: OK` for this file while opening it raises
    # `PackageNotFoundError`, and `template_docx` is the cover base, so the
    # build dies later with an error that never names the file.
    fake = tmp_path / "plantilla.docx"
    fake.write_text("esto no es un docx", encoding="utf-8")

    assert FilesystemContentProbeAdapter().probe(fake).container_ok is False


def test_a_real_docx_is_reported_as_readable(tmp_path):
    from docx import Document

    real = tmp_path / "real.docx"
    Document().save(real)

    assert FilesystemContentProbeAdapter().probe(real).container_ok is True


def test_a_file_with_no_container_format_is_left_alone(tmp_path):
    # Fail-open, as the port requires: the flag answers "does it open as the
    # container its extension implies", and a `.md` implies none. Reporting
    # False there would flag every plain-text source as broken.
    note = tmp_path / "nota.md"
    note.write_text("# hola\n", encoding="utf-8")

    assert FilesystemContentProbeAdapter().probe(note).container_ok is True


def test_a_missing_file_stays_fail_open(tmp_path):
    assert FilesystemContentProbeAdapter().probe(tmp_path / "no-existe.docx").container_ok is True
