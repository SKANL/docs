# tests/unit/application/test_status_service.py
"""Unit coverage for StatusService (design.md item I, `doc status`):
aggregate-and-read summary over context/sections/ingest/figures/output --
introduces no new state (ADR-I). Same real-repository-on-tmp_path style as
tests/integration/test_context_pack_service.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application.context import ContextService
from docs.application.review import ReviewService
from docs.application.status import StatusService
from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Section, SectionContract, Template, Topic
from docs.domain.normative import NormativeSettings
from docs.domain.sections import apply_stamp, with_frontmatter
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_NORMATIVE = NormativeSettings(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)


def _template() -> Template:
    return Template(
        type="documento-generico",
        title="Doc",
        context_schema=ContextSchema(topics=[Topic(id="alumno", title="Alumno", required=True, multiline=True)]),
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="conclusiones", title="Conclusiones", order=2, required=True),
        ],
        section_contracts={
            "introduccion": SectionContract(required_content=["alcance"]),
            "conclusiones": SectionContract(),
        },
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def document_repo(workspace: Workspace) -> JsonDocumentRepository:
    repo = JsonDocumentRepository(workspace)
    workspace.doc_root("alpha").mkdir(parents=True)
    repo.write_document(Document(id="alpha", title="Alpha", template="documento-generico"))
    repo.register(DocumentSummary(id="alpha", title="Alpha", template="documento-generico", created_at="t"))
    return repo


@pytest.fixture
def service(workspace: Workspace, document_repo: JsonDocumentRepository) -> StatusService:
    section_repo = JsonSectionRepository(workspace)
    context_repo = JsonContextRepository(workspace)
    context_service = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
    review_service = ReviewService(section_repo)
    return StatusService(section_repo, context_service, review_service, document_repo)


def _config(tmp_path: Path) -> dict:
    doc_root = tmp_path / "documents" / "alpha"
    return {
        "paths": {
            "inbox_dir": str(doc_root / "inbox"),
            "sections_dir": str(doc_root / "sections"),
            "output_draft_dir": str(doc_root / "output" / "draft"),
            "output_final_dir": str(doc_root / "output" / "final"),
            "runs_dir": str(doc_root / "runs"),
        },
    }


def test_status_summary_reports_fresh_document(tmp_path, service):
    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert (status.context_filled, status.context_total) == (0, 1)
    assert status.context_missing_topics == ["alumno"]
    assert (status.sections_authored, status.sections_total) == (0, 2)
    assert status.sections_missing == ["introduccion", "conclusiones"]
    assert status.sections_scaffold == []
    assert status.sections_needs_review == []
    assert status.ingest_ran is False
    assert status.classification_pending == 0
    assert status.figures_count == 0
    assert status.output_draft_exists is False
    assert status.output_final_exists is False
    assert status.lifecycle == "draft"
    assert status.build_version is None


def test_status_summary_reports_partially_completed_document(tmp_path, workspace, service):
    doc_root = workspace.doc_root("alpha")
    section_repo = JsonSectionRepository(workspace)

    # Context filled.
    service.context_service.set("alpha", _template(), "alumno", "Texto introductorio.")

    # `introduccion`: scaffold section, still contains PENDIENTE + harness-scaffold stamp.
    scaffold_metadata = {"managed_by": "docs-harness", "authored_by": "harness-scaffold", "schema": 3}
    section_repo.write_section(
        "alpha", 1, "introduccion",
        with_frontmatter("PENDIENTE: documentar alcance con evidencia del ledger, contexto o fuentes.", scaffold_metadata),
    )

    # `conclusiones`: authored (real content, no PENDIENTE, non-scaffold authored_by), no gaps.
    conclusiones_body = "# Conclusiones\n\nCierre del trabajo."
    authored_metadata = apply_stamp({}, "conclusiones", "Conclusiones", conclusiones_body, "hash", "ai-agent", "gpt", "t")
    section_repo.write_section("alpha", 2, "conclusiones", with_frontmatter(conclusiones_body, authored_metadata))

    # Ingest artifacts.
    inbox_dir = doc_root / "inbox"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "_detection.json").write_text("{}", encoding="utf-8")
    (inbox_dir / "_classification-queue.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": {
                    "a.pdf": {"proposed_role": "manual", "confidence": "high", "signals": [], "confirmed_role": None},
                    "b.pdf": {"proposed_role": "manual", "confidence": "high", "signals": [], "confirmed_role": "manual"},
                },
            }
        ),
        encoding="utf-8",
    )

    # Figure catalog.
    sections_dir = doc_root / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-catalog.json").write_text(
        json.dumps({"figures": [{"id": "fig-aaaaaaaa"}, {"id": "fig-bbbbbbbb"}]}), encoding="utf-8"
    )

    # Output draft artifact.
    output_draft_dir = doc_root / "output" / "draft"
    output_draft_dir.mkdir(parents=True)
    (output_draft_dir / "tesina-draft.docx").write_text("x", encoding="utf-8")

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert (status.context_filled, status.context_total) == (1, 1)
    assert status.context_missing_topics == []
    assert (status.sections_authored, status.sections_total) == (2, 2)
    assert status.sections_missing == []
    assert status.sections_scaffold == ["introduccion"]
    # `introduccion` has a missing required_content gap AND is scaffold -> flagged.
    assert status.sections_needs_review == ["introduccion"]
    assert status.ingest_ran is True
    assert status.classification_pending == 1
    assert status.figures_count == 2
    assert status.output_draft_exists is True
    assert status.output_final_exists is False


# --- Phase 6: lifecycle + build version (item F, spec: document-lifecycle) -


def test_status_summary_reports_final_lifecycle_after_mark_final(tmp_path, document_repo, service):
    document = document_repo.read_document("alpha")
    document_repo.write_document(document.model_copy(update={"lifecycle": "final"}))

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert status.lifecycle == "final"


def test_status_summary_reports_latest_build_version_from_runs_dir(tmp_path, service):
    runs_dir = tmp_path / "documents" / "alpha" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "1-pipeline-assemble.json").write_text(json.dumps({"build_version": 1}), encoding="utf-8")
    (runs_dir / "2-pipeline-assemble.json").write_text(json.dumps({"build_version": 2}), encoding="utf-8")

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert status.build_version == 2
