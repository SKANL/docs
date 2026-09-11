from __future__ import annotations

from pathlib import Path

from PIL import Image

from docs.application.render_verification import RenderVerificationService
from docs.domain.artifacts import RenderProfile
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
