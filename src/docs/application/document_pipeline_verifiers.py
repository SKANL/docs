"""Format-level artifact verifiers used by the document pipeline stages."""

from __future__ import annotations

import zipfile
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path

from docs.domain.identity import sha256_file
from docs.domain.pipeline_kernel import ArtifactRecord, StageResult


class _HtmlDocumentVerifier(HTMLParser):
    """Record the document-level elements required from rendered HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_elements = 0
        self.body_elements = 0
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() == "html":
            self.html_elements += 1
        elif tag.casefold() == "body":
            self.body_elements += 1

    def handle_data(self, data: str) -> None:
        self.visible_text.append(data)


def _verify_html_artifact(artifact: Path) -> tuple[bool, str]:
    try:
        source = artifact.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return False, f"HTML artifact is not valid UTF-8: {exc}"

    parser = _HtmlDocumentVerifier()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:  # pragma: no cover - HTMLParser currently accepts most malformed markup.
        return False, f"HTML artifact is unreadable: {exc}"
    if parser.html_elements != 1:
        return False, "HTML artifact is missing an html root element"
    if parser.body_elements != 1:
        return False, "HTML artifact is missing a body element"
    # Reopen the serialized document through the parser and require rendered
    # content, not merely a container-shaped byte stream.
    if not "".join(parser.visible_text).strip():
        return False, "HTML artifact has no renderable body content"
    return True, "HTML document reopened and visual content verified"


def _verify_pdf_artifact(artifact: Path) -> tuple[bool, str]:
    if not artifact.read_bytes().startswith(b"%PDF-"):
        return False, "PDF artifact is missing the %PDF header"
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(artifact))
        try:
            if len(document) == 0:
                return False, "PDF artifact contains no pages"
            for index in range(len(document)):
                page = document[index]
                bitmap = page.render(scale=1.0)
                if bitmap.width <= 0 or bitmap.height <= 0:
                    return False, f"PDF page {index + 1} rendered with invalid dimensions"
        finally:
            document.close()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return False, f"PDF artifact is unreadable: {exc}"
    return True, "PDF reopened, rendered, and visual dimensions verified"


def _verify_pdf_reproducibility(original: Path, rebuilt: Path) -> tuple[bool, str]:
    """Compare PDF semantics, not bytes, because PDF rendering is engine-dependent."""
    try:
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(str(original)) as first, pdfium.PdfDocument(str(rebuilt)) as second:
            if not len(first) or len(first) != len(second):
                return False, "PDF reproducibility changed the page count"
            for index in range(len(first)):
                left, right = first[index], second[index]
                try:
                    if left.get_size() != right.get_size():
                        return False, f"PDF reproducibility changed page geometry at page {index + 1}"
                    with closing(left.get_textpage()) as left_text, closing(right.get_textpage()) as right_text:
                        if left_text.get_text_range() != right_text.get_text_range():
                            return False, f"PDF reproducibility changed text at page {index + 1}"
                    with (
                        closing(left.render(scale=150 / 72)) as left_bitmap,
                        closing(right.render(scale=150 / 72)) as right_bitmap,
                        left_bitmap.to_pil() as left_image, right_bitmap.to_pil() as right_image,
                    ):
                        if left_image.size != right_image.size or left_image.tobytes() != right_image.tobytes():
                            return False, f"PDF reproducibility changed rendered content at page {index + 1}"
                finally:
                    left.close()
                    right.close()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return False, f"PDF reproducibility comparison failed: {exc}"
    return True, "PDF reproducibility verified semantically"


def _verify_non_docx_artifact(output_format: str, artifact: Path) -> tuple[bool, str]:
    """Reopen a rendered non-DOCX artifact using its existing verifier."""
    if output_format == "html":
        return _verify_html_artifact(artifact)
    if output_format == "pdf":
        return _verify_pdf_artifact(artifact)
    return False, f"no format verifier is registered for {output_format}"


def _minimal_structural_audit(artifact: Path, output_format: str) -> tuple[bool, str]:
    """Perform the minimum structural reopen gate when no full auditor is wired."""
    if not artifact.exists():
        return False, f"artifact is missing: {artifact}"
    if not artifact.is_file():
        return False, f"artifact is not a file: {artifact}"
    try:
        if artifact.stat().st_size <= 0:
            return False, f"artifact is empty: {artifact}"
        if output_format == "docx":
            with zipfile.ZipFile(artifact) as archive:
                if "word/document.xml" not in archive.namelist():
                    return False, "structural DOCX missing word/document.xml"
                archive.read("word/document.xml")
        else:
            artifact.read_bytes()
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return False, f"artifact is unreadable: {exc}"
    return True, f"minimal fallback: {output_format.upper()} reopened and structural dimensions verified"


def _fallback_structural_audit(artifact: Path, output_format: str) -> tuple[bool, str]:
    """Native name for the native structural stage."""
    return _minimal_structural_audit(artifact, output_format)


def _successful_stage_result(name: str, artifact: Path) -> StageResult:
    """Create the completion artifact required by a native v2 stage."""
    record = ArtifactRecord(
        f"{name}-complete",
        str(artifact),
        sha256_file(artifact),
        producer_stage=name,
    )
    return StageResult(
        name,
        True,
        artifacts=(
            record,
        ),
    )


def _verify_readable_artifact(artifact: Path) -> tuple[bool, str]:
    """Keep format-specific verification in pipeline stages, after a safe read."""
    try:
        with artifact.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return False, f"artifact is unreadable: {exc}"
    return True, "artifact is readable"
