from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docs.domain.review import Issue


class StructuralAuditAdapter:
    """Declarative structural checks for DOCX and PDF; prose review is elsewhere."""

    def audit(self, artifact_path: Path, rules: dict[str, object]) -> list[Issue]:
        suffix = artifact_path.suffix.lower()
        if suffix == ".docx":
            return self._audit_docx(artifact_path, rules)
        if suffix == ".pdf":
            return self._audit_pdf(artifact_path, rules)
        return [Issue("warning", f"No hay auditoría estructural para {suffix or 'este formato'}.", "structure.unsupported")]

    def _audit_docx(self, artifact_path: Path, rules: dict[str, object]) -> list[Issue]:
        from docx import Document

        document = Document(str(artifact_path))
        issues: list[Issue] = []
        headings = [p.text.strip() for p in document.paragraphs if p.style and p.style.name.startswith("Heading") and p.text.strip()]
        expected_headings = self._string_list(rules.get("headings"))
        if expected_headings and not self._ordered(headings, expected_headings):
            issues.append(Issue("error", "Los headings no respetan el orden declarado.", "structure.headings.order"))
        expected_sections = self._string_list(rules.get("sections"))
        if expected_sections and not self._ordered(headings, expected_sections):
            issues.append(Issue("error", "Las secciones no respetan el orden declarado.", "structure.sections.order"))

        self._minimum(issues, "tables", len(document.tables), rules.get("tables"), "tabla")
        image_count = len(document.inline_shapes)
        self._minimum(issues, "images", image_count, rules.get("images"), "imagen")
        captions = sum(bool(re.match(r"^(Figura|Figure|Tabla|Table)\s+\d+", p.text.strip(), re.IGNORECASE)) for p in document.paragraphs)
        caption_rules = self._mapping(rules.get("captions"))
        if caption_rules.get("required") and image_count and captions < image_count:
            issues.append(Issue("error", "Faltan captions para imágenes declaradas.", "structure.captions.missing"))
        reference_rules = self._mapping(rules.get("references"))
        if reference_rules.get("required") and not any(re.fullmatch(r"(references|referencias)", heading, re.IGNORECASE) for heading in headings):
            issues.append(Issue("error", "Falta una sección de referencias.", "structure.references.missing"))
        metadata_rules = self._mapping(rules.get("metadata"))
        for field in self._string_list(metadata_rules.get("required")):
            if not getattr(document.core_properties, field, None):
                issues.append(Issue("error", f"Falta metadato requerido: {field}.", "structure.metadata.missing"))
        self._page_size(
            issues,
            [(float(s.page_width or 0) / 12700, float(s.page_height or 0) / 12700) for s in document.sections],
            rules,
        )
        return issues

    def _audit_pdf(self, artifact_path: Path, rules: dict[str, object]) -> list[Issue]:
        import pypdfium2 as pdfium

        issues: list[Issue] = []
        try:
            document = pdfium.PdfDocument(str(artifact_path))
            try:
                if len(document) == 0:
                    issues.append(Issue("error", "El PDF no contiene páginas.", "structure.pdf.unreadable"))
                else:
                    self._page_size(issues, [document[index].get_size() for index in range(len(document))], rules)
            finally:
                document.close()
        except (OSError, RuntimeError, ValueError) as exc:
            issues.append(Issue("error", f"PDF no legible: {exc}", "structure.pdf.unreadable"))
        return issues

    @staticmethod
    def _string_list(value: object) -> list[str]:
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _mapping(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _ordered(actual: list[str], expected: list[str]) -> bool:
        position = 0
        for value in actual:
            if position < len(expected) and value.casefold() == expected[position].casefold():
                position += 1
        return position == len(expected)

    def _minimum(self, issues: list[Issue], name: str, actual: int, rule: object, label: str) -> None:
        minimum = self._mapping(rule).get("minimum", 0)
        if isinstance(minimum, int) and actual < minimum:
            issues.append(Issue("error", f"Se requieren al menos {minimum} {label}(s).", f"structure.{name}.minimum"))

    def _page_size(self, issues: list[Issue], dimensions: list[tuple[float, float]], rules: dict[str, object]) -> None:
        expected = rules.get("page_size")
        if not isinstance(expected, tuple) or len(expected) != 2:
            return
        for width, height in dimensions:
            if abs(width - expected[0]) > 0.5 or abs(height - expected[1]) > 0.5:
                issues.append(Issue("error", "El tamaño de página no coincide con la regla declarada.", "structure.page_size"))
                return
