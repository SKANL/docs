from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, UnidentifiedImageError

from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationFinding, VerificationReport
from docs.infrastructure.verification.html_inspection import HtmlInspection


class RenderVerificationAdapter:
    """Best-effort, format-neutral verification using installed render adapters."""

    def verify(
        self, artifact: ArtifactRef, profile: RenderProfile, preview_dir: Path | None = None
    ) -> VerificationReport:
        path = Path(artifact.path)
        suffix = path.suffix.lower()
        findings = self._format_findings(path, profile)
        try:
            if suffix == ".pdf":
                findings.extend(self._verify_pdf(path, profile, preview_dir))
            elif suffix == ".docx":
                findings.extend(self._verify_docx(path, profile, preview_dir))
            elif suffix in {".html", ".htm"}:
                findings.extend(self._verify_html(path, profile, preview_dir))
            else:
                findings.extend(self._verify_image(path, profile, preview_dir))
        except (OSError, RuntimeError, UnidentifiedImageError, ValueError) as exc:
            findings.append(VerificationFinding("render.open", f"No se pudo abrir {path.name}: {exc}"))
        return VerificationReport(
            artifact=artifact,
            findings=findings,
            checked_artifacts=[artifact],
        )

    def _verify_pdf(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        import pypdfium2 as pdfium

        findings: list[VerificationFinding] = []
        document = pdfium.PdfDocument(str(path))
        try:
            if len(document) == 0:
                return [VerificationFinding("render.pages.empty", "El PDF no contiene páginas.")]
            findings.extend(self._pdf_accessibility(document))
            rendered_previews = preview_dir is not None
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                    findings.extend(self._dimensions(index + 1, width, height, profile))
                    findings.extend(self._pdf_objects(page, index + 1))
                    bitmap = page.render(scale=profile.preview_dpi / 72)
                    try:
                        with bitmap.to_pil() as image:
                            findings.append(VerificationFinding("render.page.valid", f"Página {index + 1} válida.", "info", page=index + 1))
                            if self._is_blank(image):
                                findings.append(self._blank_finding(f"Página {index + 1} vacía.", profile))
                            if preview_dir is not None:
                                image.save(preview_dir / f"{path.stem}-p{index + 1:02d}.png")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            if profile.require_previews and not rendered_previews:
                findings.append(VerificationFinding("render.previews.required", "Se requieren previews, pero no se indicó directorio."))
            return findings
        finally:
            document.close()

    @staticmethod
    def _pdf_accessibility(document: object) -> list[VerificationFinding]:
        import pypdfium2 as pdfium

        try:
            tagged = pdfium.raw.FPDFCatalog_IsTagged(document)
        except (AttributeError, RuntimeError) as exc:
            return [VerificationFinding("accessibility.pdf.tags_unverified", f"PDF tagged structure cannot be verified: {exc}", "warning", dimension="accessibility")]
        if not tagged:
            return [VerificationFinding("accessibility.pdf.untagged", "PDF has no declared tagged structure; reading order and alternatives cannot be verified.", "warning", dimension="accessibility")]
        return [VerificationFinding("accessibility.pdf.tags_unverified", "PDF declares tags, but reading order and tag semantics are not validated by this technical check.", "warning", dimension="accessibility")]

    @staticmethod
    def _pdf_objects(page: Any, number: int) -> list[VerificationFinding]:
        """Inspect top-level bounds, not arbitrary clip paths or semantic layout."""
        import pypdfium2 as pdfium

        findings: list[VerificationFinding] = []
        left, bottom, right, top = page.get_bbox()
        # Nested form coordinates need composed matrices; do not compare them
        # directly with page coordinates (which would report false clipping).
        for obj in page.get_objects(max_depth=1):
            if obj.type in {pdfium.raw.FPDF_PAGEOBJ_TEXT, pdfium.raw.FPDF_PAGEOBJ_IMAGE}:
                x0, y0, x1, y1 = obj.get_bounds()
                if x0 < left - .5 or y0 < bottom - .5 or x1 > right + .5 or y1 > top + .5:
                    findings.append(VerificationFinding("render.content.clipping", "PDF text/image bounds extend outside the page crop box.", "warning", page=number,
                                                        evidence={"bounds": [x0, y0, x1, y1], "page_bounds": [left, bottom, right, top]}))
            if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                try:
                    bitmap = obj.get_bitmap()
                    try:
                        with bitmap.to_pil() as image:
                            image.load()
                    finally:
                        bitmap.close()
                except (OSError, RuntimeError, ValueError) as exc:
                    findings.append(VerificationFinding("render.image.invalid", f"PDF image cannot be decoded: {exc}", page=number))
        return findings

    def _verify_docx(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        from docx import Document

        document = Document(str(path))
        findings = [VerificationFinding("render.open", "DOCX abrible.", "info")]
        for index, section in enumerate(document.sections, start=1):
            findings.extend(
                self._dimensions(
                    index, float(section.page_width or 0) / 12700, float(section.page_height or 0) / 12700, profile
                )
            )
        findings.append(
            VerificationFinding("render.pages.unavailable", "El conteo de páginas DOCX requiere renderizador opcional.", "warning")
        )
        if profile.require_previews:
            findings.append(
                VerificationFinding("render.previews.unavailable", "Los previews DOCX requieren LibreOffice y no están cableados aún.")
            )
        return findings

    def _verify_html(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        text = path.read_text(encoding="utf-8")
        findings = [VerificationFinding("render.open", "HTML abrible.", "info")]
        inspection = HtmlInspection(text)
        findings.extend(inspection.accessibility())
        findings.extend(inspection.visual(path, profile))
        if not text.strip():
            findings.append(VerificationFinding("render.content.empty", "El HTML está vacío."))
        if profile.require_previews:
            findings.append(VerificationFinding("render.previews.unavailable", "Los previews HTML requieren navegador opcional."))
        return findings

    def _verify_image(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        with Image.open(path) as image:
            findings = self._dimensions(1, image.width, image.height, profile)
            findings.append(VerificationFinding("render.page.valid", "Imagen válida.", "info"))
            if self._is_blank(image):
                findings.append(self._blank_finding("Imagen vacía.", profile))
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
                image.copy().save(preview_dir / f"{path.stem}-p01.png")
            elif profile.require_previews:
                findings.append(VerificationFinding("render.previews.required", "Se requieren previews, pero no se indicó directorio."))
            return findings

    @staticmethod
    def _dimensions(page: int, width: float, height: float, profile: RenderProfile) -> list[VerificationFinding]:
        if profile.expected_page_size is None:
            return []
        expected_width, expected_height = profile.expected_page_size
        if abs(width - expected_width) > 0.5 or abs(height - expected_height) > 0.5:
            return [
                VerificationFinding(
                    "render.dimensions",
                    f"Página {page} mide {width:.1f}×{height:.1f}; se esperaba {expected_width:.1f}×{expected_height:.1f}.",
                )
            ]
        return []

    @staticmethod
    def _is_blank(image: Image.Image) -> bool:
        rgb = image.convert("RGB")
        return ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).getbbox() is None

    @staticmethod
    def _blank_finding(message: str, profile: RenderProfile) -> VerificationFinding:
        severity = "warning" if profile.allow_blank_pages else "error"
        return VerificationFinding("render.page.blank", message, severity)

    @staticmethod
    def _format_findings(path: Path, profile: RenderProfile) -> list[VerificationFinding]:
        actual = RenderVerificationAdapter._actual_format(path)
        expected = {"htm": "html", "jpg": "image", "jpeg": "image", "png": "image"}.get(
            profile.format.casefold().lstrip("."), profile.format.casefold().lstrip(".")
        )
        if actual == expected:
            return []
        return [
            VerificationFinding(
                "render.format_mismatch",
                f"El perfil espera formato {expected}, pero el archivo {path.name} es {actual} por extensión/tipo de medio.",
            )
        ]

    @staticmethod
    def _actual_format(path: Path) -> str:
        suffix = path.suffix.casefold()
        if suffix == ".docx":
            return "docx"
        if suffix in {".html", ".htm"}:
            return "html"
        try:
            import filetype

            guessed = filetype.guess(path)
        except (OSError, ValueError):
            guessed = None
        if guessed is not None:
            if guessed.mime == "application/pdf":
                return "pdf"
            if guessed.mime.startswith("image/"):
                return "image"
        if suffix == ".pdf":
            return "pdf"
        return "image"
