# tests/integration/test_doctor_service.py
from __future__ import annotations

import sys
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository

_MINIMAL_TEMPLATE_FIELDS = {
    "type": "template",
    "title": "T",
    "structure": [],
    "sections": [{"id": "intro", "title": "Intro", "order": 1}],
    "section_contracts": {"intro": {}},
    "context_schema": {},
}


def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    return DoctorService(JsonEvidenceRepository(), asset_service, SystemToolResolverAdapter())


def test_run_doctor_uses_injected_tool_resolver_not_shutil_which(tmp_path, monkeypatch):
    class _FakeToolResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _FakeToolResolver())
    config = _config(tmp_path)

    result = service.run_doctor("doc-1", config)

    pandoc_check = next(c for c in result.checks if c.name == "pandoc")
    libreoffice_check = next(c for c in result.checks if c.name == "libreoffice")
    assert pandoc_check.ok is True
    assert pandoc_check.detail == "/fake/pandoc"
    assert libreoffice_check.ok is False


def _config(tmp_path, **paths):
    config = dict(_MINIMAL_TEMPLATE_FIELDS)
    config["paths"] = {"rules_manifest": str(tmp_path / "manual-rules.json"), **paths}
    return config


def test_run_doctor_flags_missing_context_and_manual_dirs(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path, context_dir=str(tmp_path / "missing_context"), manual_dir=str(tmp_path / "missing_manual"))

    result = service.run_doctor("doc1", config)

    context_check = next(c for c in result.checks if c.name == "context_dir")
    assert context_check.ok is False


def test_run_doctor_passes_context_dir_check_when_directory_exists(tmp_path):
    (tmp_path / "context").mkdir()
    service = _service(tmp_path)
    config = _config(tmp_path, context_dir=str(tmp_path / "context"))

    result = service.run_doctor("doc1", config)

    context_check = next(c for c in result.checks if c.name == "context_dir")
    assert context_check.ok is True


def test_run_doctor_rules_manifest_check_is_not_required(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    manifest_check = next(c for c in result.checks if c.name == "rules_manifest")
    assert manifest_check.ok is False
    assert manifest_check.required is False


def test_run_doctor_python_check_is_always_ok_and_reports_sys_executable(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    python_check = next(c for c in result.checks if c.name == "python")
    assert python_check.ok is True
    assert python_check.detail == sys.executable


def test_run_doctor_reports_asset_missing_when_structure_references_one(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)
    config["structure"] = [{"type": "cover_from_asset", "asset": "cover"}]

    result = service.run_doctor("doc1", config)

    asset_check = next(c for c in result.checks if c.name == "asset:cover")
    assert asset_check.ok is False
    assert asset_check.required is False


def test_run_doctor_does_not_include_png_pipeline_checks(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    names = {c.name for c in result.checks}
    assert names.isdisjoint({"poppler_pdfinfo", "poppler_pdftoppm", "pypdfium2", "visual_render_backend", "documents_render_docx"})


def test_run_doctor_gh_check_required_only_when_strict(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    non_strict = service.run_doctor("doc1", config, strict=False)
    strict = service.run_doctor("doc1", config, strict=True)

    assert next(c for c in non_strict.checks if c.name == "gh").required is False
    assert next(c for c in strict.checks if c.name == "gh").required is True


def test_run_doctor_result_passed_reflects_rules_config_failure(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)
    config["section_contracts"] = {}  # missing contract for "intro" -> rules_config fails

    result = service.run_doctor("doc1", config)

    assert result.passed is False
