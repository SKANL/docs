# tests/integration/test_context_pack_service.py
from pathlib import Path

import pytest

from docs.application.context_pack import ContextPackService
from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.models.template import Section, SectionContract, Template
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_REVIEW_KWARGS = dict(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)

_REVIEW_DOCUMENT_KWARGS = dict(
    manifest_exists=True,
    manifest_size=10,
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> ContextPackService:
    section_repo = JsonSectionRepository(workspace)
    evidence_repo = JsonEvidenceRepository()
    return ContextPackService(
        section_repo,
        evidence_repo,
        EvidenceService(evidence_repo),
        ReviewService(section_repo),
    )


def _template() -> Template:
    return Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract(required_content=["alcance"])},
    )


def _config(tmp_path: Path) -> dict:
    return {
        "paths": {
            "prompts_dir": str(tmp_path / "prompts"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
        },
    }


def test_pack_context_includes_required_content_checklist(tmp_path, workspace, service):
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "- [ ] alcance" in text


def test_pack_context_writes_under_context_subdir(tmp_path, workspace, service):
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    assert out_path == workspace.doc_root("doc-1") / "sections" / "_context" / "001-introduccion.context.md"


def test_pack_context_includes_role_prompt_content_when_present(tmp_path, workspace, service):
    prompts_dir = Path(tmp_path / "prompts")
    prompts_dir.mkdir()
    (prompts_dir / "section-author.md").write_text("Redacta con rigor.", encoding="utf-8")
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    assert "Redacta con rigor." in out_path.read_text(encoding="utf-8")


def test_pack_context_includes_apa_prompt_only_when_apa_required(tmp_path, workspace, service):
    template = Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract(apa_required=True)},
    )
    prompts_dir = Path(tmp_path / "prompts")
    prompts_dir.mkdir()
    (prompts_dir / "apa7-citation-auditor.md").write_text("Audita citas APA.", encoding="utf-8")
    out_path = service.pack_context(
        "doc-1", template, "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    assert "Audita citas APA." in out_path.read_text(encoding="utf-8")


def test_pack_context_filters_ledger_lines_by_keyword(tmp_path, workspace, service):
    config = _config(tmp_path)
    ledger_path = Path(config["paths"]["fact_ledger"])
    ledger_path.write_text(
        "# Fact Ledger\n\n- El alcance está definido.\n- Otro hecho no relacionado de cocina.\n",
        encoding="utf-8",
    )
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", config, **_REVIEW_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "El alcance está definido." in text
    assert "Otro hecho no relacionado de cocina." not in text


def test_pack_context_includes_manifest_facts_matching_keywords(tmp_path, workspace, service):
    config = _config(tmp_path)
    service.evidence_repository.write_manifest(
        Path(config["paths"]["source_manifest"]),
        {"facts": [{"classification": "confirmado", "claim": "El alcance fue validado.", "source": "a"}]},
    )
    out_path = service.pack_context("doc-1", _template(), "introduccion", config, **_REVIEW_KWARGS)
    assert "El alcance fue validado." in out_path.read_text(encoding="utf-8")


def test_pack_context_caps_manifest_facts_at_40(tmp_path, workspace, service):
    config = _config(tmp_path)
    facts = [{"classification": "confirmado", "claim": f"Alcance hecho {i}"} for i in range(50)]
    service.evidence_repository.write_manifest(Path(config["paths"]["source_manifest"]), {"facts": facts})
    out_path = service.pack_context("doc-1", _template(), "introduccion", config, **_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert text.count("Alcance hecho") == 40


def test_pack_context_includes_current_draft_and_findings_when_section_exists(tmp_path, workspace, service):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text("Sin titulo.\n", encoding="utf-8")
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "## Borrador actual" in text
    assert "structure.missing_title" in text


def test_pack_context_notes_missing_draft_when_section_absent(tmp_path, workspace, service):
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "Aún no existe" in text
    assert "build-section introduccion" in text


def test_pack_context_section_contract_model_dump_surfaces_extra_keys(tmp_path, workspace, service):
    """Parity risk vs legacy raw json.dumps(contract_dict, ...): confirm pydantic
    extra="allow" fields on SectionContract survive model_dump() into the
    rendered contract JSON block, not just the typed fields."""
    template = Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={
            "introduccion": SectionContract.model_validate(
                {"required_content": ["alcance"], "custom_legacy_key": "valor-no-tipado"}
            )
        },
    )
    out_path = service.pack_context(
        "doc-1", template, "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert '"custom_legacy_key": "valor-no-tipado"' in text


def test_pack_context_document_lists_missing_section_as_no(tmp_path, workspace, service):
    out_path = service.pack_context_document(
        "doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "| introduccion | no | – | – | – | – |" in text


def test_pack_context_document_reports_word_count_and_pending_for_existing_section(
    tmp_path, workspace, service
):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text(
        '---\n{"authored_by": "agent-x", "model": "opus"}\n---\n# Introducción\n\nPENDIENTE: completar.\n',
        encoding="utf-8",
    )
    out_path = service.pack_context_document(
        "doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS
    )
    text = out_path.read_text(encoding="utf-8")
    assert "| introduccion | sí |" in text
    assert "| sí | agent-x | opus |" in text


def test_pack_context_document_writes_to_000_document_path(tmp_path, workspace, service):
    out_path = service.pack_context_document(
        "doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS
    )
    assert out_path == workspace.doc_root("doc-1") / "sections" / "_context" / "000-document.context.md"


def test_pack_context_document_includes_ledger_text_when_present(tmp_path, workspace, service):
    config = _config(tmp_path)
    Path(config["paths"]["fact_ledger"]).write_text(
        "# Fact Ledger\n\n- Hecho canónico.\n", encoding="utf-8"
    )
    out_path = service.pack_context_document(
        "doc-1", _template(), config, review_document_kwargs=_REVIEW_DOCUMENT_KWARGS
    )
    assert "Hecho canónico." in out_path.read_text(encoding="utf-8")


def test_pack_context_document_omits_ledger_section_when_ledger_absent(tmp_path, workspace, service):
    out_path = service.pack_context_document(
        "doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS
    )
    assert "## Hechos canónicos (ledger)" not in out_path.read_text(encoding="utf-8")
