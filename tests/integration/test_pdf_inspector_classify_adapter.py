import pytest

from docs.infrastructure.pdf.pdf_inspector_classify_adapter import PdfInspectorClassifyAdapter

pytest.importorskip("pdf_inspector")


@pytest.fixture
def text_pdf(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 4))
    fig.text(0.1, 0.8, "Hello world", fontsize=18)
    path = tmp_path / "text.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path


def test_a_text_pdf_is_classified_text_based(text_pdf):
    result = PdfInspectorClassifyAdapter().classify(text_pdf)
    assert result.pdf_type == "text_based"
    assert result.page_count == 1


def test_a_single_column_page_reports_no_columns(text_pdf):
    assert PdfInspectorClassifyAdapter().classify(text_pdf).pages_with_columns == []


def test_pages_needing_ocr_is_advisory_not_a_gate(text_pdf):
    """A `text_based` PDF can still list pages needing OCR when its text layer
    is sparse -- measured on exactly this fixture. `pdf_type` is the gate; if
    this were treated as one, a perfectly translatable document would be
    refused."""
    result = PdfInspectorClassifyAdapter().classify(text_pdf)
    assert result.pdf_type == "text_based"
    assert isinstance(result.pages_needing_ocr, list)


def test_the_classification_is_a_plain_domain_object(text_pdf):
    result = PdfInspectorClassifyAdapter().classify(text_pdf)
    assert isinstance(result.has_encoding_issues, bool)
    assert isinstance(result.pages_with_columns, list)
