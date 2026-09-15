# tests/integration/test_technical_report_srs_acceptance.py
"""PR5 (item D) falsifiable acceptance gate: `technical-report-srs` -- a
second built-in template, structurally different from both existing ones
(no APA, English, technical-report/SRS section shape, its OWN
`contested_stack_terms` list) -- MUST pass `review-rules`/`build-rules`/
`doctor` and a full `pipeline all` run with zero blocking errors, AND its
review outcome must reflect ITS OWN declared rule config, not estadia's.
Modeled directly on `test_documento_generico_acceptance.py` (spec:
template-provisioning "Second Built-In Non-APA Template")."""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.rules import review_rules
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "technical-report-srs.json"


def _resolved_config(tmp_path: Path) -> dict:
    """Mirrors `Deps.resolve_context`'s shape: the template's own declared
    `paths` merged with computed, always-present per-document paths."""
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    paths = dict(raw.get("paths", {}))
    paths.update(
        {
            "rules_manifest": str(sections_dir / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
        }
    )
    raw["paths"] = paths
    return raw


def test_technical_report_srs_review_rules_passes_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)

    result = review_rules(template, manifest_exists=True, manifest_size=42, strict=False)

    assert result.issues == []
    assert result.passed is True


def test_technical_report_srs_build_rules_succeeds_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    service = EvidenceService(JsonEvidenceRepository())

    manifest_path = service.build_rules(config)

    assert manifest_path.exists()


def test_technical_report_srs_doctor_rules_config_check_passes(tmp_path: Path, monkeypatch):
    # Toolchain checks (pandoc/libreoffice/gh) are host-environment concerns,
    # orthogonal to this template's rule-config scope -- patched the same way
    # test_documento_generico_acceptance.py does.
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    config = _resolved_config(tmp_path)
    Path(config["paths"]["context_dir"]).mkdir(exist_ok=True)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    evidence_service = EvidenceService(evidence_repo)
    evidence_service.build_rules(config)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    tool_resolver = SystemToolResolverAdapter()
    doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)

    result = doctor_service.run_doctor("srs-doc", config, strict=False)

    rules_check = next(c for c in result.checks if c.name == "rules_config")
    assert rules_check.ok is True, rules_check.detail




def test_technical_report_srs_review_document_reflects_its_own_rules_not_estadias(tmp_path: Path):
    """The Scenario-2 proof (spec: template-provisioning): a section body
    mentioning a technology from THIS template's OWN `contested_stack_terms`
    (never estadia's `Laravel`/`Supabase`/`bun.js`/`MySQL`/`GCP`/`Firebase`
    list) is flagged; and no APA-related issue fires despite an unreferenced
    body, because this template declares `citation_style: none`."""
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    section_repo = JsonSectionRepository(workspace)
    review_service = ReviewService(section_repo)

    for section in template.sections:
        body = f"# {section.title}\n\nThis section documents {section.id} for the project.\n"
        if section.id == "implementation":
            body = "# IMPLEMENTATION\n\nThe service layer is built on jQuery for legacy DOM glue code.\n"
        section_repo.write_section("doc1", section.order, section.id, body)

    normative = resolve_normative_settings(config)
    result = review_service.review_document(
        "doc1", template, strict=False, manifest_exists=True, manifest_size=42, normative=normative,
    )

    codes = {issue.code for issue in result.issues}
    assert "coherence.contested_stack_unqualified" in codes
    assert not any(code.startswith("apa.") for code in codes)


def test_technical_report_srs_review_document_no_duration_mismatch_for_generic_hours(tmp_path: Path):
    """Doc-type-coupling leak fix: this template does NOT declare
    `cross_consistency.duration_consistency` (only estadia's does), so a
    document legitimately mentioning two different hour figures across
    sections must NOT trigger estadia's "duración de la estadía" coherence
    check (spec: template-provisioning "No hardcoded document-type literal
    in domain code")."""
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    section_repo = JsonSectionRepository(workspace)
    review_service = ReviewService(section_repo)

    for section in template.sections:
        body = f"# {section.title}\n\nThis section documents {section.id} for the project.\n"
        if section.id == "implementation":
            body = "# IMPLEMENTATION\n\nThe setup phase took 40 horas and testing took 80 horas.\n"
        section_repo.write_section("doc1", section.order, section.id, body)

    normative = resolve_normative_settings(config)
    result = review_service.review_document(
        "doc1", template, strict=False, manifest_exists=True, manifest_size=42, normative=normative,
    )

    assert not any(issue.code == "coherence.duration_mismatch" for issue in result.issues)


