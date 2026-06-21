# tests/integration/test_review_service.py
from pathlib import Path

import pytest

from docs.domain.models.template import Section, SectionContract, Template
from docs.domain.workspace import Workspace
from docs.application.review import ReviewService
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> ReviewService:
    return ReviewService(JsonSectionRepository(workspace))


def _template(**overrides) -> Template:
    defaults = dict(
        type="tesina",
        title="Tesina",
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="referencias", title="Referencias", order=2, required=False),
        ],
        section_contracts={},
    )
    defaults.update(overrides)
    return Template(**defaults)


def _write_section(workspace: Workspace, doc_id: str, order: int, section_id: str, body: str, metadata: dict | None = None) -> Path:
    sections_dir = workspace.doc_root(doc_id) / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    path = sections_dir / f"{order:03d}-{section_id}.md"
    if metadata is not None:
        import json

        text = "---\n" + json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n---\n" + body
    else:
        text = body
    path.write_text(text, encoding="utf-8")
    return path


def test_review_document_flags_missing_required_section(workspace: Workspace, service: ReviewService):
    template = _template()
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_section" in codes


def test_review_document_flags_missing_sections_dir(workspace: Workspace, service: ReviewService):
    template = _template(sections=[])
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_sections_dir" in codes


def test_review_document_prefixes_section_issue_messages_with_filename(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="Sin titulo principal.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    title_issues = [i for i in result.issues if i.code == "structure.missing_title"]
    assert len(title_issues) == 1
    assert title_issues[0].message.startswith("001-introduccion.md: ")


def test_review_document_strict_flags_pendiente_at_document_level(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nPENDIENTE: completar.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=True,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "content.pending_not_allowed" in codes


def test_review_document_strict_flags_missing_flow_terms(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto sin terminos de flujo.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=True,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    flow_issues = [i for i in result.issues if i.code == "coherence.missing_flow"]
    assert len(flow_issues) == 1
    assert "problema" in flow_issues[0].message


def test_review_document_skips_optional_missing_section_without_error(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="referencias", title="Referencias", order=2, required=False)]
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_section" not in codes


def test_review_document_includes_cross_consistency_issues(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="referencias", title="Referencias", order=2, required=False),
        ]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nComo señala Pérez (2020), el sistema funciona.\n",
        metadata={"section_id": "introduccion"},
    )
    _write_section(
        workspace, "doc-1", 2, "referencias",
        body="# Referencias\n\n(sin referencias)\n",
        metadata={"section_id": "referencias"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "coherence.citation_without_global_reference" in codes


def test_review_document_includes_rules_issues_when_manifest_missing(workspace: Workspace, service: ReviewService):
    template = _template(sections=[])
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=False,
        manifest_size=0,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    messages = [issue.message for issue in result.issues]
    assert any("manual-rules.json" in message for message in messages)
