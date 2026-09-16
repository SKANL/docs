from __future__ import annotations

from pathlib import Path

from docx import Document
from PIL import Image

from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import ArtifactRef, RenderProfile, VerificationFinding
from docs.infrastructure.verification.render_verification_adapter import RenderVerificationAdapter


def _write_blank_pdf(path: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)


def test_pdf_verification_emits_preview_and_page_findings(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        pdf,
        RenderProfile(format="pdf", expected_page_size=(612, 792), require_previews=True, allow_blank_pages=True),
        tmp_path / "previews",
    )

    assert (tmp_path / "previews" / "report-p01.png").is_file()
    assert any(finding.code == "render.page.valid" for finding in report.findings)
    assert any(finding.code == "render.page.blank" for finding in report.findings)
    assert report.passed is True


def test_docx_verification_uses_shared_renderer_for_pages_previews_and_baseline(tmp_path):
    docx = tmp_path / "report.docx"
    Document().save(docx)
    baseline = tmp_path / "baseline"
    baseline.mkdir()

    class Renderer:
        def render_docx_to_pdf(self, _config, _docx_path, output_dir):
            pdf = output_dir / "report.pdf"
            _write_blank_pdf(pdf)
            return pdf

    previews = tmp_path / "previews"
    report = RenderVerificationService(RenderVerificationAdapter(docx_renderer=Renderer())).verify(
        docx,
        RenderProfile(
            format="docx",
            expected_page_size=(612, 792),
            require_previews=True,
            allow_blank_pages=True,
            baseline_dir=baseline,
            preview_stem="report",
        ),
        previews,
    )

    assert (previews / "report-p01.png").is_file()
    assert any(f.code == "render.pages.count" and f.evidence["count"] == 1 for f in report.findings)
    assert any(f.code == "render.toolchain" for f in report.findings)
    assert len(report.checked_artifacts) == 2
    assert any(f.code == "visual.baseline_missing" for f in report.findings)


def test_docx_verification_forwards_config_and_omits_ephemeral_pdf_without_previews(tmp_path):
    docx = tmp_path / "report.docx"
    Document().save(docx)
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}, "visual_qa": {"allow_blank_pages": True}}
    calls = []

    class Renderer:
        def render_docx_to_pdf(self, received_config, _docx_path, output_dir):
            calls.append(received_config)
            pdf = output_dir / "report.pdf"
            _write_blank_pdf(pdf)
            return pdf

    report = RenderVerificationAdapter(docx_renderer=Renderer()).verify(
        ArtifactRef(path=docx.as_posix(), sha256="source"),
        RenderProfile(format="docx", allow_blank_pages=True),
        config=config,
    )

    assert calls == [config]
    assert len(report.checked_artifacts) == 1
    assert not (tmp_path / "report.pdf").exists()


def test_image_verification_detects_wrong_dimensions(tmp_path):
    image = tmp_path / "cover.png"
    Image.new("RGB", (200, 100), "white").save(image)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        image, RenderProfile(format="image", expected_page_size=(100, 100))
    )

    assert any(finding.code == "render.dimensions" and finding.severity == "error" for finding in report.findings)


def test_pdf_verification_rejects_blank_page_when_profile_disallows_it(tmp_path):
    pdf = tmp_path / "blank.pdf"
    _write_blank_pdf(pdf)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))

    assert report.passed is False
    assert any(finding.code == "render.page.blank" and finding.severity == "error" for finding in report.findings)


def test_pdf_verification_warns_for_blank_page_when_profile_allows_it(tmp_path):
    pdf = tmp_path / "blank.pdf"
    _write_blank_pdf(pdf)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        pdf, RenderProfile(format="pdf", allow_blank_pages=True)
    )

    assert report.passed is True
    assert any(finding.code == "render.page.blank" and finding.severity == "warning" for finding in report.findings)


def test_render_verification_reports_profile_format_mismatch(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="image"))

    assert report.passed is False
    assert any(finding.code == "render.format_mismatch" and finding.severity == "error" for finding in report.findings)

# Static HTML checks are deliberately narrower than a WCAG conformance audit.
def test_html_verification_reports_accessibility_gaps(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html><body><h2>Start</h2><h4>Jump</h4><img src="bad.png"></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    codes = {finding.code for finding in report.findings}
    assert {
        "accessibility.html.lang", "accessibility.html.h1", "accessibility.html.heading_order",
        "accessibility.html.main", "accessibility.html.header", "accessibility.html.alt",
    } <= codes


def test_html_valid_static_accessibility_does_not_claim_layout_verified(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header>'
                    '<main><h2>Section</h2><p>Content</p></main></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert not [f for f in report.findings if f.dimension == "accessibility" and f.severity == "error"]
    assert any(f.code == "render.layout.unavailable" and f.severity == "warning" for f in report.findings)


def test_html_browser_qa_replaces_static_layout_fallback_and_writes_viewport_screenshots(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header>'
                    '<main><p>Content</p></main></body></html>')

    class BrowserQa:
        def verify(self, path, profile, preview_dir):
            assert path == html
            assert profile.browser_viewports == ((800, 600), (390, 844))
            assert preview_dir is not None
            (preview_dir / "report-browser-800x600.png").write_bytes(b"desktop")
            (preview_dir / "report-browser-390x844.png").write_bytes(b"mobile")
            return [
                VerificationFinding(
                    "render.browser.checked", "Browser layout checked.", "info", dimension="visual",
                    evidence={"viewport": [800, 600]},
                ),
                VerificationFinding(
                    "render.browser.checked", "Browser layout checked.", "info", dimension="visual",
                    evidence={"viewport": [390, 844]},
                ),
            ]

    report = RenderVerificationService(RenderVerificationAdapter(browser_qa=BrowserQa())).verify(
        html,
        RenderProfile(format="html", browser_viewports=((800, 600), (390, 844)), require_previews=True),
        tmp_path / "previews",
    )

    assert (tmp_path / "previews" / "report-browser-800x600.png").is_file()
    assert (tmp_path / "previews" / "report-browser-390x844.png").is_file()
    assert any(f.code == "render.browser.checked" for f in report.findings)
    assert not any(f.code == "render.layout.unavailable" for f in report.findings)


def test_html_browser_qa_failure_keeps_static_fallback_and_reports_unavailability(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header><main>Text</main></body></html>')

    class BrowserQa:
        def verify(self, path, profile, preview_dir):
            raise RuntimeError("browser executable missing")

    report = RenderVerificationService(RenderVerificationAdapter(browser_qa=BrowserQa())).verify(
        html, RenderProfile(format="html"), tmp_path / "previews"
    )

    assert any(f.code == "render.browser.unavailable" and f.severity == "warning" for f in report.findings)
    assert any(f.code == "render.layout.unavailable" for f in report.findings)


def test_html_browser_findings_keep_static_fallback_when_browser_returns_no_checked_evidence(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header><main>Text</main></body></html>')

    class BrowserQa:
        def verify(self, path, profile, preview_dir):
            return [VerificationFinding("render.browser.warning", "Only partial browser evidence.", "warning", dimension="visual")]

    report = RenderVerificationService(RenderVerificationAdapter(browser_qa=BrowserQa())).verify(
        html, RenderProfile(format="html"), tmp_path / "previews"
    )

    assert any(f.code == "render.layout.unavailable" for f in report.findings)


def test_html_browser_partial_viewport_evidence_keeps_static_fallback(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header><main>Text</main></body></html>')

    class BrowserQa:
        def verify(self, path, profile, preview_dir):
            return [VerificationFinding(
                "render.browser.checked", "One viewport checked.", "info", dimension="visual",
                evidence={"viewport": list(profile.browser_viewports[0])},
            )]

    report = RenderVerificationService(RenderVerificationAdapter(browser_qa=BrowserQa())).verify(
        html, RenderProfile(format="html", browser_viewports=((800, 600), (390, 844))), tmp_path / "previews"
    )

    assert any(f.code == "render.layout.unavailable" for f in report.findings)


def test_html_browser_screenshot_evidence_is_hashed(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header><main>Text</main></body></html>')

    class BrowserQa:
        def verify(self, path, profile, preview_dir):
            screenshot = preview_dir / "report-browser-800x600.png"
            screenshot.write_bytes(b"desktop")
            return [VerificationFinding("render.browser.checked", "Browser layout checked.", "info", dimension="visual")]

    report = RenderVerificationService(RenderVerificationAdapter(browser_qa=BrowserQa())).verify(
        html, RenderProfile(format="html", browser_viewports=((800, 600),)), tmp_path / "previews"
    )

    finding = next(f for f in report.findings if f.code == "render.browser.checked")
    assert finding.evidence["screenshot_sha256"] == __import__("hashlib").sha256(b"desktop").hexdigest()
    assert finding.evidence["screenshot_path"].endswith("report-browser-800x600.png")


def test_html_detects_empty_body_not_nonempty_source(tmp_path):
    html = tmp_path / "empty.html"
    html.write_text('<html><head><title>Title</title><style>body{color:red}</style></head>'
                    '<body><script>hello()</script><!-- comment --></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert any(f.code == "render.page.blank" for f in report.findings)


def test_html_detects_invalid_images_and_declared_clipping(tmp_path):
    html = tmp_path / "report.html"
    (tmp_path / "broken.png").write_bytes(b"not an image")
    html.write_text('<html><body><div style="width:40px; height:30px; overflow:hidden">'
                    '<img src="broken.png" width="80" height="60" alt="Chart"></div></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert {"render.image.invalid", "render.content.clipping"} <= {f.code for f in report.findings}


def test_pdf_reports_absence_of_tags_in_addition_to_technical_findings(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))
    assert any(f.code == "accessibility.pdf.untagged" and f.severity == "warning" for f in report.findings)
    assert any(f.code == "render.page.blank" for f in report.findings)


def test_pdf_accessibility_reports_missing_language_and_title_metadata(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)

    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))

    codes = {finding.code for finding in report.findings}
    assert {"accessibility.pdf.language_missing", "accessibility.pdf.title_missing"} <= codes
    assert all("WCAG" not in finding.message for finding in report.findings if finding.dimension == "accessibility")


def test_pdf_detects_objects_outside_page_bounds(tmp_path):
    import pypdfium2 as pdfium

    pdf = tmp_path / "clipped.pdf"
    document = pdfium.PdfDocument.new()
    page = document.new_page(100, 100)
    bitmap = pdfium.PdfBitmap.from_pil(Image.new("RGB", (10, 10), "black"))
    obj = pdfium.PdfImage.new(document)
    obj.set_bitmap(bitmap)
    obj.set_matrix(pdfium.PdfMatrix(80, 0, 0, 40, 60, 10))
    page.insert_obj(obj)
    page.gen_content()
    document.save(pdf)
    bitmap.close()
    page.close()
    document.close()
    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))
    assert any(f.code == "render.content.clipping" and f.page == 1 for f in report.findings)


def test_html_templates_do_not_satisfy_accessibility_or_visible_content(tmp_path):
    html = tmp_path / "template.html"
    html.write_text('<html lang="en"><body><template><header><h1>Invisible</h1></header>'
                    '<main><img src="unused.png" alt=""></main></template></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    codes = {finding.code for finding in report.findings}
    assert {"render.page.blank", "accessibility.html.main", "accessibility.html.header"} <= codes
    assert "render.image.invalid" not in codes


def test_html_inline_vector_content_is_not_reported_as_empty(tmp_path):
    html = tmp_path / "vector.html"
    html.write_text('<html lang="en"><body><svg width="100" height="100">'
                    '<rect width="100" height="100" fill="black"/></svg></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert not any(f.code == "render.page.blank" for f in report.findings)
    assert any(f.code == "render.layout.unavailable" for f in report.findings)


def test_corrupt_html_encoding_becomes_technical_finding(tmp_path):
    html = tmp_path / "encoding.html"
    html.write_bytes(b"\xff\xfe<html>")
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert not report.passed and any(f.code == "render.open" for f in report.findings)


def test_html_image_alternatives_allow_decorative_but_reject_missing(tmp_path):
    import base64
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "black").save(buffer, format="PNG")
    source = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    html = tmp_path / "images.html"
    html.write_text(f'<html lang="en"><body><header><h1>Title</h1></header><main>'
                    f'<img src="{source}" alt=""><img src="{source}" alt="Chart"></main></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(html, RenderProfile(format="html"))
    assert not any(f.code in {"render.page.blank", "render.image.invalid", "accessibility.html.alt"} for f in report.findings)


def test_pdf_tag_capability_failure_is_explicit(tmp_path, monkeypatch):
    import pypdfium2 as pdfium

    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    monkeypatch.delattr(pdfium.raw, "FPDFCatalog_IsTagged")
    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))
    assert any(f.code == "accessibility.pdf.tags_unverified" and f.severity == "warning" for f in report.findings)
    assert any(f.code == "render.page.valid" for f in report.findings)


def test_html_required_previews_do_not_silently_pass(tmp_path):
    html = tmp_path / "report.html"
    html.write_text('<html lang="en"><body><header><h1>Title</h1></header><main>Text</main></body></html>')
    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        html, RenderProfile(format="html", require_previews=True), tmp_path / "previews",
    )
    assert not report.passed
    assert any(f.code == "render.previews.unavailable" for f in report.findings)
    assert not list(tmp_path.glob("previews/*.png"))


def test_pdf_invalid_embedded_image_is_reported_without_losing_page_checks(tmp_path):
    pdf = tmp_path / "broken-image.pdf"
    stream = b"q 50 0 0 50 10 10 cm /Image1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R /Resources << /XObject << /Image1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 10 /Height 10 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length 6 >>\nstream\nbroken\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    pdf.write_bytes(data)
    report = RenderVerificationService(RenderVerificationAdapter()).verify(pdf, RenderProfile(format="pdf"))
    assert any(f.code == "render.image.invalid" and f.page == 1 for f in report.findings)
    assert any(f.code == "render.page.valid" for f in report.findings)
    assert not report.passed


def test_pdf_preview_baseline_reports_changed_missing_and_extra_pages(tmp_path):
    import pypdfium2 as pdfium

    pdf = tmp_path / "report.pdf"
    with pdfium.PdfDocument.new() as document:
        first = document.new_page(612, 792)
        second = document.new_page(612, 792)
        document.save(pdf)
        first.close()
        second.close()
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    Image.new("RGB", (1275, 1650), "black").save(baseline / "report-p01.png")
    Image.new("RGB", (1275, 1650), "white").save(baseline / "report-p03.png")

    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        pdf,
        RenderProfile(
            format="pdf",
            baseline_dir=baseline,
            minimum_similarity=1.0,
        ),
        tmp_path / "previews",
    )

    assert {"visual.baseline_changed", "visual.baseline_missing", "visual.baseline_extra_page"} <= {
        finding.code for finding in report.findings
    }


def test_pdf_previews_remove_obsolete_pages_before_baseline_comparison(tmp_path):
    import shutil

    import pypdfium2 as pdfium

    artifact = tmp_path / "report.pdf"
    previews = tmp_path / "previews"
    baseline = tmp_path / "baseline"
    service = RenderVerificationService(RenderVerificationAdapter())

    def write_pages(count):
        with pdfium.PdfDocument.new() as document:
            for _ in range(count):
                page = document.new_page(100, 100)
                page.close()
            document.save(artifact)

    write_pages(2)
    service.verify(artifact, RenderProfile(format="pdf", allow_blank_pages=True), previews)
    shutil.copytree(previews, baseline)
    write_pages(1)
    report = service.verify(artifact, RenderProfile(format="pdf", allow_blank_pages=True, baseline_dir=baseline), previews)
    assert {finding.code for finding in report.findings} >= {"visual.baseline_extra_page"}
    assert [p.name for p in previews.glob("*.png")] == ["report-p01.png"]
    assert (baseline / "report-p02.png").exists()


def test_preview_cleanup_never_mutates_explicit_baseline_directory(tmp_path):
    pdf = tmp_path / "report.pdf"
    _write_blank_pdf(pdf)
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    page = baseline / "precious.png"
    Image.new("RGB", (10, 10), "black").save(page)
    before = page.read_bytes()
    report = RenderVerificationService(RenderVerificationAdapter()).verify(
        pdf, RenderProfile(format="pdf", baseline_dir=baseline, allow_blank_pages=True), baseline,
    )
    assert not report.passed
    assert page.read_bytes() == before
    assert [path.name for path in baseline.iterdir()] == ["precious.png"]
