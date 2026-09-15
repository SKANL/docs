from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document

from docs.application.format_audit import FormatAuditService
from docs.application.review import ReviewService
from docs.application.review_stages import ReviewStageService
from docs.application.structural_audit import StructuralAuditService
from docs.domain.models.template import Template
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import Issue, ReviewDimension, ReviewResult
from docs.domain.workspace import Workspace
from docs.infrastructure.audit.structural_audit_adapter import StructuralAuditAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


def _service(tmp_path: Path) -> ReviewStageService:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return ReviewStageService(
        structural_audit=StructuralAuditService(StructuralAuditAdapter()),
        format_audit=FormatAuditService(PythonDocxAuditAdapter()),
        document_review=ReviewService(JsonSectionRepository(workspace)),
        rules_manifest_state=lambda _config: (True, 1),
    )


def _document(tmp_path: Path, heading: str = "INTRODUCCION") -> Path:
    document = Document()
    document.add_heading(heading, level=1)
    document.add_paragraph("Contenido de prueba.")
    path = tmp_path / "fixture.docx"
    document.save(path)
    return path


def _template() -> Template:
    return Template(type="fixture", title="Fixture")


def test_review_stages_run_real_adapters_for_a_compliant_fixture_document(tmp_path: Path) -> None:
    artifact = _document(tmp_path)
    service = _service(tmp_path)

    outcomes = service.run_all(
        document_id="fixture",
        artifact_path=artifact,
        config={"apa7": {"citation_style": "none"}},
        template=_template(),
        policy=PipelinePolicy(PipelineMode.draft),
        rebuild=lambda output: shutil.copyfile(artifact, output),
        scratch_dir=tmp_path / "rebuild",
    )

    assert tuple(outcomes) == (
        "structural-audit",
        "editorial-review",
        "evidence-review",
        "consistency-review",
        "accessibility-review",
        "visual-review",
        "reproducibility-check",
    )
    assert all(outcome.ok for outcome in outcomes.values())
    assert all(not outcome.warnings for outcome in outcomes.values())


def test_blocking_visual_finding_degrades_only_in_draft_policy(tmp_path: Path) -> None:
    artifact = _document(tmp_path, heading="Introduccion")
    service = _service(tmp_path)
    config = {"apa7": {"citation_style": "none"}}

    draft = service.visual_review(artifact, config, PipelinePolicy(PipelineMode.draft))
    strict = service.visual_review(artifact, config, PipelinePolicy(PipelineMode.strict))
    release = service.visual_review(artifact, config, PipelinePolicy(PipelineMode.release))

    assert draft.ok is True
    assert draft.warnings == ("Título de primer orden no está en mayúsculas sostenidas: `Introduccion`.",)
    assert strict.ok is False
    assert set(draft.warnings).issubset(strict.errors)
    assert release.ok is False
    assert set(draft.warnings).issubset(release.errors)


def test_run_stage_executes_only_the_requested_review_adapter(tmp_path: Path) -> None:
    artifact = _document(tmp_path)
    service = _service(tmp_path)

    outcome = service.run_stage(
        "visual-review",
        document_id="fixture",
        artifact_path=artifact,
        config={"apa7": {"citation_style": "none"}},
        template=_template(),
        policy=PipelinePolicy(PipelineMode.draft),
        rebuild=lambda _output: (_ for _ in ()).throw(AssertionError("unexpected rebuild")),
        scratch_dir=tmp_path / "rebuild",
    )

    assert outcome.ok is True


def test_evidence_review_applies_pipeline_policy_to_evidence_findings(tmp_path: Path) -> None:
    class Review:
        def review_document(self, *args: object, **kwargs: object) -> ReviewResult:
            return ReviewResult([
                Issue(
                    "warning",
                    "evidence needs support",
                    code="evidence.missing_support",
                    dimension=ReviewDimension.EVIDENCE,
                )
            ])

    service = ReviewStageService(
        structural_audit=StructuralAuditService(StructuralAuditAdapter()),
        format_audit=FormatAuditService(PythonDocxAuditAdapter()),
        document_review=Review(),
        rules_manifest_state=lambda _config: (True, 1),
    )

    outcome = service.run_stage(
        "evidence-review",
        document_id="fixture",
        artifact_path=tmp_path / "unused.docx",
        config={},
        template=_template(),
        policy=PipelinePolicy(PipelineMode.strict),
        rebuild=lambda output: output,
        scratch_dir=tmp_path / "rebuild",
    )

    assert outcome.ok is False
    assert outcome.errors == ("evidence needs support",)
    assert not outcome.warnings


def _multiformat_service(tmp_path: Path) -> ReviewStageService:
    from docs.application.render_verification import RenderVerificationService
    from docs.infrastructure.verification.render_verification_adapter import RenderVerificationAdapter

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return ReviewStageService(
        structural_audit=StructuralAuditService(StructuralAuditAdapter()),
        format_audit=FormatAuditService(PythonDocxAuditAdapter()),
        document_review=ReviewService(JsonSectionRepository(workspace)),
        rules_manifest_state=lambda _: (True, 1),
        render_verification=RenderVerificationService(RenderVerificationAdapter()),
    )


def test_html_accessibility_stage_uses_static_checks_not_docx_audit(tmp_path):
    artifact = tmp_path / "document.html"
    artifact.write_text('<html><body><h2>Content</h2></body></html>')
    outcome = _multiformat_service(tmp_path).accessibility_review(artifact, {}, PipelinePolicy())
    assert not outcome.ok
    assert "language" in outcome.detail and "h1" in outcome.detail and "landmark" in outcome.detail


def test_accessibility_and_visual_dimensions_are_independent(tmp_path):
    artifact = tmp_path / "document.html"
    artifact.write_text('<html lang="en"><body><header><h1>Title</h1></header>'
                        '<main><h2>Content</h2><p>Text.</p></main></body></html>')
    service = _multiformat_service(tmp_path)
    accessibility = service.accessibility_review(artifact, {}, PipelinePolicy(PipelineMode.strict))
    visual = service.visual_review(artifact, {}, PipelinePolicy(PipelineMode.strict))
    assert accessibility.ok and not accessibility.warnings
    assert not visual.ok and "Browser renderer unavailable" in visual.detail
    assert "WARNING" not in visual.detail  # Report and gate must reflect the same policy.


def test_pdf_tag_warning_degrades_only_according_to_policy(tmp_path):


    artifact = tmp_path / "document.pdf"
    _write_blank_pdf(artifact)
    service = _multiformat_service(tmp_path)
    draft = service.accessibility_review(artifact, {}, PipelinePolicy())
    assert draft.ok and any("tagged structure" in message for message in draft.warnings)
    for policy in (PipelinePolicy(PipelineMode.strict), PipelinePolicy(PipelineMode.release),
                   PipelinePolicy(warning_codes=("accessibility.pdf.untagged",))):
        assert not service.accessibility_review(artifact, {}, policy).ok
    artifact.write_bytes(b"not a pdf")
    assert not service.accessibility_review(artifact, {}, PipelinePolicy()).ok


def test_visual_stage_reuses_pdf_renderer_and_preview_directory(tmp_path):


    artifact = tmp_path / "document.pdf"
    _write_blank_pdf(artifact)
    previews = tmp_path / "qa"
    result = _multiformat_service(tmp_path).visual_review(
        artifact, {"paths": {"output_qa_dir": str(previews)}}, PipelinePolicy(),
    )
    assert not result.ok and "vacía" in result.detail
    assert list(previews.rglob("*.png"))


def test_visual_stage_honors_blank_page_profile(tmp_path):


    artifact = tmp_path / "document.pdf"
    _write_blank_pdf(artifact)
    config = {"visual_qa": {"allow_blank_pages": True, "expected_page_size": [612, 792]}}
    service = _multiformat_service(tmp_path)
    assert service.visual_review(artifact, config, PipelinePolicy()).ok
    assert not service.visual_review(artifact, config, PipelinePolicy(PipelineMode.strict)).ok
    config["visual_qa"]["expected_page_size"] = [100, 100]
    assert not service.visual_review(artifact, config, PipelinePolicy()).ok


def test_multiformat_stage_without_render_port_reports_capability_gap(tmp_path):
    artifact = tmp_path / "document.html"
    artifact.write_text('<html><body>text</body></html>')
    for operation in (_service(tmp_path).accessibility_review, _service(tmp_path).visual_review):
        draft = operation(artifact, {}, PipelinePolicy())
        strict = operation(artifact, {}, PipelinePolicy(PipelineMode.strict))
        assert draft.ok and "not configured" in draft.detail
        assert not strict.ok


def _write_blank_pdf(path):
    import pypdfium2 as pdfium

    with pdfium.PdfDocument.new() as document:
        page = document.new_page(612, 792)
        document.save(path)
        page.close()


def test_missing_artifact_is_not_degraded_as_missing_renderer(tmp_path):
    result = _service(tmp_path).visual_review(tmp_path / "missing.pdf", {}, PipelinePolicy())
    assert not result.ok


def test_visual_profile_does_not_treat_false_string_as_permission_for_blank_pages(tmp_path):
    artifact = tmp_path / "document.pdf"
    _write_blank_pdf(artifact)
    result = _multiformat_service(tmp_path).visual_review(
        artifact, {"visual_qa": {"allow_blank_pages": "false"}}, PipelinePolicy(),
    )
    assert not result.ok and "profile" in result.detail.lower()
