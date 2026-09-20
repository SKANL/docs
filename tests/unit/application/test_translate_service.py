import pytest

from docs.application.translate import TranslateService, UntranslatablePdfError
from docs.domain.block_grouping import TextRun
from docs.domain.ports.pdf_classify_port import PdfClassification
from docs.domain.ports.pdf_text_edit_port import WriteDiagnostic, WriteReport


class FakeClassifier:
    def __init__(self, pdf_type="text_based", columns=None):
        self._type, self._columns = pdf_type, columns or []

    def classify(self, path):
        return PdfClassification(self._type, 1, [], self._columns, False)


class FakeEditor:
    def __init__(self, runs=None, write_report=None):
        # `runs if runs is not None`, never `runs or [...]`: an EMPTY list is
        # a meaningful value here (a PDF with no text), and truthiness would
        # silently replace it with the default.
        default = [TextRun("Hello world", 10.0, 700.0, 90.0, 14.0, 0, 12.0)]
        self._runs = default if runs is None else runs
        self._write_report = write_report
        self.written = None

    def read_runs(self, path):
        return self._runs

    def write_blocks(self, src, out, replacements):
        self.written = replacements
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 fake\n")
        return self._write_report or WriteReport(
            blocks_written=len(replacements), fonts_substituted=len(replacements)
        )


class FakeTranslator:
    engine_id = "fake-llm-v1"

    def __init__(self, responses=None):
        self.responses, self.calls = responses or {}, []

    def translate(self, text, source_lang, target_lang):
        self.calls.append(text)
        return self.responses.get(text, f"[es] {text}")


class MemoryDict:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, source_text, translation):
        self.data[key] = translation


def _service(classifier=None, translator=None, memory=None, editor=None):
    return TranslateService(
        classifier=classifier or FakeClassifier(),
        editor=editor or FakeEditor(),
        translator=translator or FakeTranslator(),
        memory=memory if memory is not None else MemoryDict(),
    )


def test_a_scanned_pdf_is_refused_with_a_clear_reason(tmp_path):
    service = _service(classifier=FakeClassifier(pdf_type="scanned"))
    with pytest.raises(UntranslatablePdfError, match="capa de texto"):
        service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")


def test_an_image_based_pdf_is_refused_too(tmp_path):
    service = _service(classifier=FakeClassifier(pdf_type="image_based"))
    with pytest.raises(UntranslatablePdfError):
        service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")


def test_a_mixed_pdf_is_translated_because_it_has_a_text_layer(tmp_path):
    service = _service(classifier=FakeClassifier(pdf_type="mixed"))
    report = service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    assert report.blocks_translated == 1


def test_blocks_are_translated_and_counted(tmp_path):
    report = _service().translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    assert report.blocks_total == 1
    assert report.blocks_translated == 1


def test_the_second_run_hits_the_cache_and_calls_no_engine(tmp_path):
    memory, translator = MemoryDict(), FakeTranslator()
    service = _service(translator=translator, memory=memory)
    service.translate_pdf(tmp_path / "in.pdf", tmp_path / "a.pdf", "es")
    calls_after_first = len(translator.calls)
    report = service.translate_pdf(tmp_path / "in.pdf", tmp_path / "b.pdf", "es")
    assert len(translator.calls) == calls_after_first, "engine called on a cache hit"
    assert report.blocks_from_cache == 1


def test_a_refusing_engine_still_produces_a_document(tmp_path):
    translator = FakeTranslator(responses={"Hello world": "I cannot help with that."})
    report = _service(translator=translator).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert report.blocks_total == 1
    assert report.blocks_translated == 0
    assert report.output_path.exists(), "a refusal must not stop the document"


def test_an_exploding_engine_still_produces_a_document(tmp_path):
    class Exploding:
        engine_id = "boom"

        def translate(self, text, source_lang, target_lang):
            raise RuntimeError("provider down")

    report = _service(translator=Exploding()).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert report.blocks_translated == 0
    assert report.output_path.exists()


def test_a_column_page_is_reported_as_untrusted(tmp_path):
    service = _service(classifier=FakeClassifier(columns=[1]))
    report = service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    assert report.pages_untrusted == [1]


def test_a_refused_block_is_not_written_to_the_cache(tmp_path):
    memory = MemoryDict()
    translator = FakeTranslator(responses={"Hello world": "I cannot help with that."})
    _service(translator=translator, memory=memory).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert memory.data == {}, "a refusal must never be cached as a translation"


def test_the_report_line_names_every_compromise(tmp_path):
    translator = FakeTranslator(responses={"Hello world": "I cannot help with that."})
    report = _service(
        translator=translator, classifier=FakeClassifier(columns=[3])
    ).translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    line = report.to_line()
    assert "0/1" in line
    assert "sin traducir" in line
    assert "3" in line


def test_post_write_verification_failures_propagate_to_the_report_line(tmp_path):
    diagnostic = WriteDiagnostic(
        code="pdf.write.overlaps_untouched_object",
        page=1,
        replacement_index=0,
        bounds=(10.0, 20.0, 40.0, 30.0),
        reference_bounds=(30.0, 20.0, 50.0, 30.0),
        object_index=2,
    )
    editor = FakeEditor(
        write_report=WriteReport(
            blocks_written=1,
            fonts_substituted=1,
            verification_diagnostics=(diagnostic,),
        )
    )

    report = _service(editor=editor).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )

    assert report.blocks_translated == 1, "translation-engine meaning must not change"
    assert report.blocks_unsafe == 1
    assert report.write_diagnostics == (diagnostic,)
    assert (
        "1 edicion geometrica insegura: "
        "pagina 1 reemplazo 1 pdf.write.overlaps_untouched_object objeto 2 "
        "bounds=(10.0,20.0,40.0,30.0) reference=(30.0,20.0,50.0,30.0)"
        in report.to_line()
    )


def test_a_pdf_with_no_text_at_all_reports_zero_blocks(tmp_path):
    report = _service(editor=FakeEditor(runs=[])).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert report.blocks_total == 0
    assert report.output_path.exists()


def test_the_target_language_is_part_of_the_cache_identity(tmp_path):
    memory, translator = MemoryDict(), FakeTranslator()
    service = _service(translator=translator, memory=memory)
    service.translate_pdf(tmp_path / "in.pdf", tmp_path / "a.pdf", "es")
    service.translate_pdf(tmp_path / "in.pdf", tmp_path / "b.pdf", "fr")
    assert len(translator.calls) == 2, "a different target must not reuse the entry"
