# tests/integration/test_documento_generico_acceptance.py
"""Front A falsifiable acceptance gate (universal-schema-harness proposal):
`documento-generico` -- a document type that declares NONE of the estadía
optional policy blocks (no `preliminaries`, no `paths.extracted_dir`, APA
disabled, no margin `advisor_overrides`) -- MUST pass `doctor`, `review-rules`,
and `build-rules` with zero errors. Before this front, every one of those
checks was hardcoded against estadía-shaped values and would have rejected
this template unconditionally.
"""
from __future__ import annotations

import json
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.application.evidence import EvidenceService
from docs.domain.models.template import Template
from docs.domain.rules import review_rules
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.domain.workspace import Workspace

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "templates" / "documento-generico.json"


def _resolved_config(tmp_path: Path) -> dict:
    """Mirrors the shape `Deps.resolve_context` produces: the template's own
    declared `paths` (here: `{}`) merged with computed, always-present
    per-document paths."""
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


def test_documento_generico_review_rules_passes_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    template = Template.model_validate(config)

    result = review_rules(template, manifest_exists=True, manifest_size=42, strict=False)

    assert result.issues == []
    assert result.passed is True


def test_documento_generico_build_rules_succeeds_with_zero_errors(tmp_path: Path):
    config = _resolved_config(tmp_path)
    service = EvidenceService(JsonEvidenceRepository())

    manifest_path = service.build_rules(config)

    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["skipped_paths"]) == {"manual_dir", "extracted_dir"}


def test_documento_generico_doctor_rules_config_check_passes(tmp_path: Path, monkeypatch):
    # Toolchain checks (pandoc/libreoffice/gh) are host-environment concerns,
    # orthogonal to this front's policy-de-hardcoding scope -- patched the
    # same way tests/integration/test_pipeline_service.py already does, so
    # this test isolates exactly what Front A changed: the "rules_config"
    # check (review_rules) and its supporting manifest/asset checks.
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_pandoc_executable", lambda paths: "pandoc"
    )
    monkeypatch.setattr(
        "docs.infrastructure.docx.tool_resolver_adapter.resolve_libreoffice_executable", lambda paths: "soffice"
    )
    monkeypatch.setattr("shutil.which", lambda name: "gh")

    config = _resolved_config(tmp_path)
    (Path(config["paths"]["context_dir"])).mkdir(exist_ok=True)
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    evidence_service = EvidenceService(evidence_repo)
    evidence_service.build_rules(config)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    tool_resolver = SystemToolResolverAdapter()
    doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)

    result = doctor_service.run_doctor("documento-generico-doc", config, strict=False)

    rules_check = next(c for c in result.checks if c.name == "rules_config")
    assert rules_check.ok is True, rules_check.detail
