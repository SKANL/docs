from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, UnidentifiedImageError

from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationFinding, VerificationReport


class RenderVerificationAdapter:
    """Best-effort, format-neutral verification using installed render adapters."""

    def verify(
        self, artifact: ArtifactRef, profile: RenderProfile, preview_dir: Path | None = None
    ) -> VerificationReport:
        path = Path(artifact.path)
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                findings = self._verify_pdf(path, profile, preview_dir)
            elif suffix == ".docx":
                findings = self._verify_docx(path, profile, preview_dir)
            elif suffix in {".html", ".htm"}:
                findings = self._verify_html(path, profile, preview_dir)
            else:
                findings = self._verify_image(path, profile, preview_dir)
        except (OSError, RuntimeError, UnidentifiedImageError, ValueError) as exc:
            findings = [VerificationFinding("render.open", f"No se pudo abrir {path.name}: {exc}")]
        return VerificationReport(artifact=artifact, findings=findings)

    def _verify_pdf(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        import pypdfium2 as pdfium

        findings: list[VerificationFinding] = []
        document = pdfium.PdfDocument(str(path))
        try:
            if len(document) == 0:
                return [VerificationFinding("render.pages.empty", "El PDF no contiene páginas.")]
            rendered_previews = preview_dir is not None
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                    findings.extend(self._dimensions(index + 1, width, height, profile))
                    bitmap = page.render(scale=profile.preview_dpi / 72)
                    image = bitmap.to_pil()
                    findings.append(VerificationFinding("render.page.valid", f"Página {index + 1} válida.", "info"))
                    if self._is_blank(image):
                        findings.append(VerificationFinding("render.page.blank", f"Página {index + 1} vacía.", "warning"))
                    if preview_dir is not None:
                        image.save(preview_dir / f"{path.stem}-p{index + 1:02d}.png")
                finally:
                    page.close()
            if profile.require_previews and not rendered_previews:
                findings.append(VerificationFinding("render.previews.required", "Se requieren previews, pero no se indicó directorio."))
            return findings
        finally:
            document.close()

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
                VerificationFinding("render.previews.unavailable", "Los previews DOCX requieren LibreOffice y no están cableados aún.", "warning")
            )
        return findings

    def _verify_html(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        text = path.read_text(encoding="utf-8")
        findings = [VerificationFinding("render.open", "HTML abrible.", "info")]
        if not text.strip():
            findings.append(VerificationFinding("render.content.empty", "El HTML está vacío."))
        if profile.require_previews:
            findings.append(VerificationFinding("render.previews.unavailable", "Los previews HTML requieren navegador opcional.", "warning"))
        return findings

    def _verify_image(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        with Image.open(path) as image:
            findings = self._dimensions(1, image.width, image.height, profile)
            findings.append(VerificationFinding("render.page.valid", "Imagen válida.", "info"))
            if self._is_blank(image):
                findings.append(VerificationFinding("render.page.blank", "Imagen vacía.", "warning"))
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
