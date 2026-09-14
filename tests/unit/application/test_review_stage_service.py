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
