# tests/integration/test_review_service.py
import hashlib
import json
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


def test_review_section_flags_issues_for_section_with_problems(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="Sin titulo principal.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_section(
        "doc-1",
        template,
        "introduccion",
        strict=False,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_title" in codes


def test_review_section_no_issues_for_clean_section(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto con suficiente contenido para la sección.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_section(
        "doc-1",
        template,
        "introduccion",
        strict=False,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    assert result.issues == []


def test_review_section_raises_when_section_file_missing(workspace: Workspace, service: ReviewService):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.review_section(
            "doc-1",
            template,
            "introduccion",
            strict=False,
            excluded_terms={},
            is_policy_file=False,
            first_person_patterns=[],
            subjective_terms=[],
            secret_patterns=[],
        )


def test_review_section_raises_when_section_id_unknown(workspace: Workspace, service: ReviewService):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.review_section(
            "doc-1",
            template,
            "no-existe",
            strict=False,
            excluded_terms={},
            is_policy_file=False,
            first_person_patterns=[],
            subjective_terms=[],
            secret_patterns=[],
        )


def test_stamp_section_raises_when_section_file_missing(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")


def test_stamp_section_sets_authored_by_and_body_hash(workspace, service):
    import hashlib

    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    text = result_path.read_text(encoding="utf-8")
    metadata_json = text.split("---\n")[1]
    metadata = json.loads(metadata_json)
    assert metadata["authored_by"] == "agent-x"
    assert metadata["stamped_at"] == "2026-06-21T00:00:00"
    assert metadata["body_hash"] == hashlib.sha256("# Introducción\n\nTexto.\n".encode("utf-8")).hexdigest()


def test_stamp_section_sets_model_when_provided(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section(
        "doc-1", template, "introduccion", "agent-x", model="opus", now="2026-06-21T00:00:00"
    )
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    assert json.loads(metadata_json)["model"] == "opus"


def test_stamp_section_synthesizes_metadata_when_file_has_no_frontmatter(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(workspace, "doc-1", 1, "introduccion", body="# Introducción\n\nSin metadata.\n", metadata=None)
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    metadata = json.loads(metadata_json)
    assert metadata["managed_by"] == "tesina-harness"
    assert metadata["schema"] == 3
    assert metadata["section_id"] == "introduccion"
    assert metadata["title"] == "Introducción"
    assert metadata["authored_by"] == "agent-x"


def test_stamp_section_preserves_unrelated_existing_metadata_fields(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion", "custom_field": "preserved"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    assert json.loads(metadata_json)["custom_field"] == "preserved"


def test_stamp_section_returns_section_path(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    written_path = _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    assert result_path == written_path


def test_build_section_writes_new_section_when_absent(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    result_path = service.build_section(
        "doc-1",
        template,
        "introduccion",
        "# Introducción\n\nContenido nuevo.\n",
        source_hash="sh",
        source_manifest_hash="smh",
        code_evidence_manifest_hash="cemh",
        rules_hash="rh",
        contract_hash="ch",
        prompt_hash="ph",
    )
    expected_path = workspace.doc_root("doc-1") / "sections" / "001-introduccion.md"
    assert result_path == expected_path
    text = result_path.read_text(encoding="utf-8")
    metadata_json = text.split("---\n")[1]
    metadata = json.loads(metadata_json)
    assert metadata["managed_by"] == "tesina-harness"
    assert metadata["authored_by"] == "harness-scaffold"
    assert metadata["section_id"] == "introduccion"
    assert metadata["title"] == "Introducción"
    assert metadata["source_hash"] == "sh"
    assert metadata["source_manifest_hash"] == "smh"
    assert metadata["code_evidence_manifest_hash"] == "cemh"
    assert metadata["rules_hash"] == "rh"
    assert metadata["contract_hash"] == "ch"
    assert metadata["prompt_hash"] == "ph"
    assert text.endswith("# Introducción\n\nContenido nuevo.\n")


def test_build_section_overwrites_when_managed_unchanged_with_metadata_drift(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    body = "# Introducción\n\nTexto estable.\n"
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body=body,
        metadata={
            "managed_by": "tesina-harness",
            "schema": 3,
            "section_id": "introduccion",
            "title": "Título viejo",
            "body_hash": body_hash,
        },
    )
    result_path = service.build_section(
        "doc-1",
        template,
        "introduccion",
        body,
        source_hash="sh",
        source_manifest_hash="smh",
        code_evidence_manifest_hash="cemh",
        rules_hash="rh",
        contract_hash="ch",
        prompt_hash="ph",
    )
    text = result_path.read_text(encoding="utf-8")
    metadata = json.loads(text.split("---\n")[1])
    assert metadata["title"] == "Introducción"
    assert metadata["source_hash"] == "sh"


def test_build_section_no_op_when_managed_unchanged_and_metadata_identical(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    body = "# Introducción\n\nTexto estable.\n"
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    metadata = {
        "managed_by": "tesina-harness",
        "authored_by": "harness-scaffold",
        "schema": 3,
        "section_id": "introduccion",
        "title": "Introducción",
        "source_hash": "sh",
        "source_manifest_hash": "smh",
        "code_evidence_manifest_hash": "cemh",
        "rules_hash": "rh",
        "contract_hash": "ch",
        "prompt_hash": "ph",
        "body_hash": body_hash,
        "last_review_hash": "",
    }
    written_path = _write_section(workspace, "doc-1", 1, "introduccion", body=body, metadata=metadata)
    before = written_path.read_text(encoding="utf-8")

    result_path = service.build_section(
        "doc-1",
        template,
        "introduccion",
        body,
        source_hash="sh",
        source_manifest_hash="smh",
        code_evidence_manifest_hash="cemh",
        rules_hash="rh",
        contract_hash="ch",
        prompt_hash="ph",
    )

    assert result_path == written_path
    after = written_path.read_text(encoding="utf-8")
    assert after == before


def test_build_section_writes_proposal_when_unmanaged_and_modified(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    written_path = _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto original del autor.\n",
        metadata={"section_id": "introduccion"},
    )
    before = written_path.read_text(encoding="utf-8")

    result_path = service.build_section(
        "doc-1",
        template,
        "introduccion",
        "# Introducción\n\nContenido generado distinto.\n",
        source_hash="sh",
        source_manifest_hash="smh",
        code_evidence_manifest_hash="cemh",
        rules_hash="rh",
        contract_hash="ch",
        prompt_hash="ph",
    )

    assert written_path.read_text(encoding="utf-8") == before
    proposal_path = workspace.doc_root("doc-1") / "sections" / "_proposals" / "001-introduccion.candidate.md"
    assert result_path == proposal_path
    assert proposal_path.exists()
    proposal_text = proposal_path.read_text(encoding="utf-8")
    assert "Contenido generado distinto" in proposal_text


def test_build_section_writes_new_section_when_no_frontmatter_and_body_matches(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    body = "# Introducción\n\nMismo contenido.\n"
    written_path = _write_section(workspace, "doc-1", 1, "introduccion", body=body, metadata=None)

    result_path = service.build_section(
        "doc-1",
        template,
        "introduccion",
        body,
        source_hash="sh",
        source_manifest_hash="smh",
        code_evidence_manifest_hash="cemh",
        rules_hash="rh",
        contract_hash="ch",
        prompt_hash="ph",
    )

    assert result_path == written_path
    text = written_path.read_text(encoding="utf-8")
    metadata = json.loads(text.split("---\n")[1])
    assert metadata["managed_by"] == "tesina-harness"
    assert text.endswith(body)


def test_resolve_section_path_returns_path_for_known_section_id(workspace, service):
    template = _template(
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="referencias", title="Referencias", order=2, required=False),
        ]
    )
    result = service.resolve_section_path("doc-1", template, "referencias")
    assert result == workspace.doc_root("doc-1") / "sections" / "002-referencias.md"


def test_resolve_section_path_raises_for_unknown_section(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.resolve_section_path("doc-1", template, "no-existe")
