from __future__ import annotations

import hashlib
import mimetypes
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageChops, UnidentifiedImageError

from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationFinding, VerificationReport
from docs.domain.visual_baseline import compare_preview_baseline
from docs.infrastructure.verification.html_browser_qa import PlaywrightHtmlBrowserQa
from docs.infrastructure.verification.html_inspection import HtmlInspection


class RenderVerificationAdapter:
    """Best-effort, format-neutral verification using installed render adapters."""

    def verify(
        self,
        artifact: ArtifactRef,
        profile: RenderProfile,
        preview_dir: Path | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> VerificationReport:
        path = Path(artifact.path)
        suffix = path.suffix.lower()
        findings = self._format_findings(path, profile)
        checked_artifacts = [artifact]
        try:
            if preview_dir is not None:
                if profile.baseline_dir is not None and (
                    preview_dir.resolve().is_relative_to(profile.baseline_dir.resolve())
                    or profile.baseline_dir.resolve().is_relative_to(preview_dir.resolve())
                ):
                    raise ValueError("Preview and baseline directories must not overlap")
                preview_dir.mkdir(parents=True, exist_ok=True)
                for stale in preview_dir.glob("*.png"):
                    stale.unlink()
            if suffix == ".pdf":
                findings.extend(self._verify_pdf(path, profile, preview_dir))
            elif suffix == ".docx":
                docx_findings, rendered_artifact = self._verify_docx(path, profile, preview_dir, config)
                findings.extend(docx_findings)
                if rendered_artifact is not None:
                    checked_artifacts.append(rendered_artifact)
            elif suffix in {".html", ".htm"}:
                findings.extend(self._verify_html(path, profile, preview_dir))
            else:
                findings.extend(self._verify_image(path, profile, preview_dir))
            if profile.baseline_dir is not None and preview_dir is not None:
                findings.extend(self._baseline_findings(preview_dir, profile))
        except (OSError, RuntimeError, UnidentifiedImageError, ValueError) as exc:
            findings.append(VerificationFinding("render.open", f"No se pudo abrir {path.name}: {exc}"))
        return VerificationReport(
            artifact=artifact,
            findings=findings,
            checked_artifacts=checked_artifacts,
            preview_hashes=(
                {
                    preview.name: hashlib.sha256(preview.read_bytes()).hexdigest()
                    for preview in sorted(preview_dir.glob("*.png"), key=lambda item: item.name)
                    if preview.is_file()
                }
                if preview_dir is not None and preview_dir.is_dir()
                else {}
            ),
        )

    def _verify_pdf(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        import pypdfium2 as pdfium

        findings: list[VerificationFinding] = []
        document = pdfium.PdfDocument(str(path))
        try:
            if len(document) == 0:
                return [VerificationFinding("render.pages.empty", "El PDF no contiene páginas.")]
            findings.append(VerificationFinding(
                "render.pages.count", f"El documento contiene {len(document)} página(s).", "info",
                evidence={"count": len(document)},
            ))
            findings.extend(self._pdf_accessibility(document, path))
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
                                image.save(preview_dir / f"{profile.preview_stem or path.stem}-p{index + 1:02d}.png")
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
    def _pdf_accessibility(document: object, path: Path) -> list[VerificationFinding]:
        import pypdfium2 as pdfium

        findings: list[VerificationFinding] = []
        try:
            tagged = pdfium.raw.FPDFCatalog_IsTagged(document)
        except (AttributeError, RuntimeError) as exc:
            findings.append(VerificationFinding(code="accessibility.pdf.tags_unverified", message=f"PDF tagged structure cannot be verified: {exc}", severity="warning", dimension="accessibility"))
        else:
            if not tagged:
                findings.append(VerificationFinding(code="accessibility.pdf.untagged", message="PDF has no declared tagged structure; reading order and alternatives cannot be verified.", severity="warning", dimension="accessibility"))
            else:
                findings.append(VerificationFinding(code="accessibility.pdf.tags_unverified", message="PDF declares tags, but reading order and tag semantics are not validated by this technical check.", severity="warning", dimension="accessibility"))

        # PDFium exposes the catalog language and document-info title without
        # adding another parser dependency. These are remediation signals, not
        # a conformance verdict.
        try:
            pdf_document = cast(Any, document)
            language = pdf_document.get_metadata_value("Lang")
            title = pdf_document.get_metadata_value("Title")
            if not str(language or "").strip():
                findings.append(VerificationFinding(
                    code="accessibility.pdf.language_missing",
                    message="PDF catalog does not declare a document language; language metadata requires author review.",
                    severity="warning", dimension="accessibility",
                ))
            if not str(title or "").strip():
                findings.append(VerificationFinding(
                    code="accessibility.pdf.title_missing",
                    message="PDF metadata does not declare a title; document title metadata requires author review.",
                    severity="warning", dimension="accessibility",
                ))
        except (AttributeError, OSError, RuntimeError, ValueError, TypeError) as exc:
            findings.append(VerificationFinding(
                code="accessibility.pdf.metadata_unverified",
                message=f"PDF language and title metadata could not be inspected: {exc}",
                severity="warning", dimension="accessibility",
            ))
        findings.extend(RenderVerificationAdapter._pdf_structure_checks(path))
        return findings

    @staticmethod
    def _pdf_structure_checks(path: Path) -> list[VerificationFinding]:
        """Inspect logical structure signals, never claim PDF conformance."""
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError as exc:
            return [VerificationFinding(code="accessibility.pdf.structure_unverified", message=f"PDF logical structure could not be inspected; optional pypdf is unavailable: {exc}", severity="warning", dimension="accessibility")]
        try:
            catalog = PdfReader(str(path)).root_object
            struct_root = catalog.get("/StructTreeRoot")
            if struct_root is None:
                return [VerificationFinding(code="accessibility.pdf.structure_missing", message="PDF has no structure tree; headings, figure alternatives, and table semantics cannot be verified.", severity="warning", dimension="accessibility")]
            nodes = RenderVerificationAdapter._pdf_structure_nodes(struct_root)
            findings: list[VerificationFinding] = []
            headings = {"/H", "/H1", "/H2", "/H3", "/H4", "/H5", "/H6"}
            if not any(str(node.get("/S", "")) in headings for node in nodes):
                findings.append(VerificationFinding(code="accessibility.pdf.heading_missing", message="PDF structure tree contains no basic heading element; heading presence could not be confirmed.", severity="warning", dimension="accessibility"))
            for node in nodes:
                role = str(node.get("/S", ""))
                if role == "/Figure" and not str(node.get("/Alt") or node.get("/ActualText") or "").strip():
                    findings.append(VerificationFinding(code="accessibility.pdf.figure_alt_missing", message="A Figure structure element has no alternative text or description.", severity="warning", dimension="accessibility"))
                if role == "/Table":
                    children = RenderVerificationAdapter._pdf_structure_nodes(node.get("/K"))
                    if not any(str(child.get("/S", "")) in {"/TR", "/TH", "/TD"} for child in children):
                        findings.append(VerificationFinding(code="accessibility.pdf.table_semantics_missing", message="A Table structure element has no detectable row/cell semantics; table structure may require specialized review.", severity="warning", dimension="accessibility"))
            findings.append(VerificationFinding(code="accessibility.pdf.structure_checked", message="PDF structure tree was inspected for basic headings, figure alternatives, and table semantics; this is not a conformance verdict.", severity="info", dimension="accessibility"))
            return findings
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return [VerificationFinding(code="accessibility.pdf.structure_unverified", message=f"PDF logical structure could not be inspected: {exc}", severity="warning", dimension="accessibility")]

    @staticmethod
    def _pdf_structure_nodes(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [node for item in value for node in RenderVerificationAdapter._pdf_structure_nodes(item)]
        try:
            node = value.get_object()
        except AttributeError:
            node = value
        if not hasattr(node, "get"):
            return []
        return [node, *RenderVerificationAdapter._pdf_structure_nodes(node.get("/K"))]

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

    def _verify_docx(
        self,
        path: Path,
        profile: RenderProfile,
        preview_dir: Path | None,
        config: Mapping[str, Any] | None = None,
    ) -> tuple[list[VerificationFinding], ArtifactRef | None]:
        from docx import Document

        document = Document(str(path))
        findings = [VerificationFinding("render.open", "DOCX abrible.", "info")]
        for index, section in enumerate(document.sections, start=1):
            findings.extend(
                self._dimensions(
                    index, float(section.page_width or 0) / 12700, float(section.page_height or 0) / 12700, profile
                )
            )
        renderer = cast(Any, self.docx_renderer)
        if renderer is None:
            findings.append(VerificationFinding(
                "render.pages.unavailable", "El conteo de páginas DOCX requiere LibreOffice.", "warning",
            ))
            if profile.require_previews:
                findings.append(VerificationFinding(
                    "render.previews.unavailable", "Los previews DOCX requieren LibreOffice.", "error",
                ))
            return findings, None

        with tempfile.TemporaryDirectory(prefix="docs_docx_qa_") as temporary:
            try:
                pdf = Path(renderer.render_docx_to_pdf(config or {}, path, Path(temporary)))
                if preview_dir is not None:
                    # Keep the rendered derivative next to the preview set so
                    # checked-artifact evidence remains readable after the
                    # private renderer workspace is cleaned up.
                    durable_pdf = preview_dir.parent / f"{path.stem}.pdf"
                    if durable_pdf.resolve() != pdf.resolve():
                        durable_pdf.parent.mkdir(parents=True, exist_ok=True)
                        durable_pdf.write_bytes(pdf.read_bytes())
                    pdf = durable_pdf
                findings.append(VerificationFinding(
                    "render.toolchain", "DOCX renderizado mediante el adaptador LibreOffice.", "info",
                    evidence={"renderer": type(renderer).__name__, "path": pdf.resolve().as_posix()},
                ))
                pdf_profile = replace(profile, format="pdf")
                findings.extend(self._verify_pdf(pdf, pdf_profile, preview_dir))
                rendered_artifact = None
                if preview_dir is not None:
                    with pdf.open("rb") as rendered_file:
                        rendered_digest = hashlib.file_digest(rendered_file, "sha256").hexdigest()
                    rendered_artifact = ArtifactRef(
                        path=pdf.resolve().as_posix(),
                        sha256=rendered_digest,
                        media_type=mimetypes.guess_type(pdf.name)[0] or "application/pdf",
                        size_bytes=pdf.stat().st_size,
                    )
                return findings, rendered_artifact
            except (OSError, RuntimeError, ValueError) as exc:
                findings.append(VerificationFinding(
                    "render.toolchain.unavailable", f"No se pudo renderizar el DOCX: {exc}",
                    "error" if profile.require_previews else "warning",
                ))
                return findings, None

    def _verify_html(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        text = path.read_text(encoding="utf-8")
        findings = [VerificationFinding("render.open", "HTML abrible.", "info")]
        inspection = HtmlInspection(text)
        findings.extend(inspection.accessibility())
        findings.extend(inspection.visual(path, profile))
        try:
            browser_findings = cast(Any, self.browser_qa).verify(path, profile, preview_dir)
        except Exception as exc:
            findings.append(VerificationFinding(
                code="render.browser.unavailable",
                message=f"Browser renderer unavailable; static HTML checks only: {exc}",
                severity="warning", dimension="visual",
            ))
        else:
            checked_viewports = sum(
                finding.code == "render.browser.checked" for finding in browser_findings
            )
            if checked_viewports == len(profile.browser_viewports):
                findings = [finding for finding in findings if finding.code != "render.layout.unavailable"]
            findings.extend(self._screenshot_evidence(browser_findings, path, profile, preview_dir))
        if not text.strip():
            findings.append(VerificationFinding("render.content.empty", "El HTML está vacío."))
        if profile.require_previews and not any(
            finding.code == "render.browser.checked" and finding.evidence.get("screenshot_sha256")
            for finding in findings
        ):
            findings.append(VerificationFinding("render.previews.unavailable", "Los previews HTML requieren navegador opcional."))
        return findings

    @staticmethod
    def _screenshot_evidence(
        findings: list[VerificationFinding], path: Path, profile: RenderProfile, preview_dir: Path | None
    ) -> list[VerificationFinding]:
        if preview_dir is None:
            return findings
        enriched: list[VerificationFinding] = []
        for finding in findings:
            if finding.code != "render.browser.checked":
                enriched.append(finding)
                continue
            viewport = finding.evidence.get("viewport")
            screenshot: Path | None
            if isinstance(viewport, list) and len(viewport) == 2:
                screenshot = preview_dir / f"{profile.preview_stem or path.stem}-browser-{viewport[0]}x{viewport[1]}.png"
            else:
                candidates = sorted(preview_dir.glob(f"{profile.preview_stem or path.stem}-browser-*.png"))
                screenshot = candidates[0] if len(candidates) == 1 else None
            if screenshot is None or not screenshot.is_file():
                enriched.append(finding)
                continue
            evidence = dict(finding.evidence)
            evidence.update({
                "screenshot_path": screenshot.resolve().as_posix(),
                "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                "screenshot_size_bytes": screenshot.stat().st_size,
            })
            enriched.append(replace(finding, evidence=evidence))
        return enriched

    def _verify_image(self, path: Path, profile: RenderProfile, preview_dir: Path | None) -> list[VerificationFinding]:
        with Image.open(path) as image:
            findings = self._dimensions(1, image.width, image.height, profile)
            findings.append(VerificationFinding("render.page.valid", "Imagen válida.", "info"))
            if self._is_blank(image):
                findings.append(self._blank_finding("Imagen vacía.", profile))
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
                image.copy().save(preview_dir / f"{profile.preview_stem or path.stem}-p01.png")
            elif profile.require_previews:
                findings.append(VerificationFinding("render.previews.required", "Se requieren previews, pero no se indicó directorio."))
            return findings

    @staticmethod
    def _baseline_findings(preview_dir: Path, profile: RenderProfile) -> list[VerificationFinding]:
        assert profile.baseline_dir is not None
        return [
            VerificationFinding(
                finding.code,
                finding.message,
                finding.severity,
                page=finding.page,
                dimension="visual",
                evidence={} if finding.similarity is None else {"similarity": finding.similarity},
            )
            for finding in compare_preview_baseline(
                preview_dir,
                profile.baseline_dir,
                minimum_similarity=profile.minimum_similarity,
                strict=profile.baseline_strict,
            )
        ]

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
    def __init__(self, browser_qa: object | None = None, docx_renderer: object | None = None) -> None:
        self.browser_qa = browser_qa if browser_qa is not None else PlaywrightHtmlBrowserQa()
        if docx_renderer is None:
            from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter

            docx_renderer = LibreOfficeQaAdapter()
        self.docx_renderer = docx_renderer
