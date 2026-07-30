# tests/integration/test_doctor_service.py
from __future__ import annotations

import json
import sys
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.ingest.content_probe_adapter import FilesystemContentProbeAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "templates"

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
    return DoctorService(
        JsonEvidenceRepository(),
        asset_service,
        SystemToolResolverAdapter(),
        content_probe=FilesystemContentProbeAdapter(),
    )


def test_run_doctor_uses_injected_tool_resolver_not_shutil_which(tmp_path, monkeypatch):
    class _FakeToolResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
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


def _rules_config_passing_config(tmp_path, **paths):
    """Like `_config`, but shaped so `review_rules` reports zero "error"
    issues (matches tests/integration/test_pipeline_service.py's
    `_valid_rules_extra`) -- needed for assertions on the overall
    `result.passed`, since `_config`'s bare `section_contracts` intentionally
    has no `required_content` and fails `rules_config` regardless of
    doctor's own manual_dir/capability checks."""
    config = _config(
        tmp_path,
        extracted_dir_policy="rules_traceability_only",
        **paths,
    )
    config["section_contracts"] = {"intro": {"required_content": ["algo"]}}
    config["preliminaries"] = {
        "roman_pagination": {"enabled": True},
        "body_pagination_start": {"section_id": "intro"},
    }
    config["format"] = {
        "page_margins_cm": {
            "cover_policy": "preserve_template",
            "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5},
        }
    }
    config["advisor_overrides"] = [{"id": "margins-2-5cm-non-cover", "status": "active"}]
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


def test_run_doctor_extracted_dir_policy_check_not_present_when_extracted_dir_absent(tmp_path):
    # spec: document-pipeline "Extracted-dir policy checked only when
    # configured" -- mirrors _check_extracted_dir_policy's own gating.
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    names = {c.name for c in result.checks}
    assert "extracted_dir_traceability_only" not in names


def test_run_doctor_extracted_dir_policy_check_passes_for_any_declared_string(tmp_path):
    # NEW-SUGGESTION-1 (verify follow-up on PR1's WARNING-2 sibling): the
    # check must verify internal consistency (a policy IS declared), never
    # compare against a hardcoded expected value like "rules_traceability_only".
    (tmp_path / "extracted").mkdir()
    service = _service(tmp_path)
    config = _config(
        tmp_path,
        extracted_dir=str(tmp_path / "extracted"),
        extracted_dir_policy="anything_else",
    )

    result = service.run_doctor("doc1", config)

    check = next(c for c in result.checks if c.name == "extracted_dir_traceability_only")
    assert check.ok is True


def test_run_doctor_extracted_dir_policy_check_fails_when_not_declared(tmp_path):
    (tmp_path / "extracted").mkdir()
    service = _service(tmp_path)
    config = _config(tmp_path, extracted_dir=str(tmp_path / "extracted"))

    result = service.run_doctor("doc1", config)

    check = next(c for c in result.checks if c.name == "extracted_dir_traceability_only")
    assert check.ok is False


def test_run_doctor_extracted_dir_policy_check_passes_for_real_reporte_estadia_tic_fixture(tmp_path):
    # WARNING-3 (fresh-context verify, PR2 fix batch) -- this is PR1's
    # CRITICAL-1 lesson repeated: a template-declared field resolved
    # correctly under synthetic unit-test parameters is NOT proof it works
    # for the real, currently-shipping fixture. Driven by the REAL
    # reporte-estadia-tic.json file, not hand-picked params.
    raw = json.loads((_FIXTURES_DIR / "reporte-estadia-tic.json").read_text(encoding="utf-8"))
    paths = dict(raw.get("paths", {}))
    paths["rules_manifest"] = str(tmp_path / "manual-rules.json")
    raw["paths"] = paths
    service = _service(tmp_path)

    result = service.run_doctor("reporte-estadia-tic-doc", raw)

    check = next(c for c in result.checks if c.name == "extracted_dir_traceability_only")
    assert check.ok is True


def test_run_doctor_extracted_dir_policy_check_absent_for_real_documento_generico_fixture(tmp_path):
    # documento-generico declares no paths.extracted_dir at all -- the check
    # must not appear (conditional gate), matching the "checked only when
    # configured" spec scenario for both real fixtures.
    raw = json.loads((_FIXTURES_DIR / "documento-generico.json").read_text(encoding="utf-8"))
    paths = dict(raw.get("paths", {}))
    paths["rules_manifest"] = str(tmp_path / "manual-rules.json")
    raw["paths"] = paths
    service = _service(tmp_path)

    result = service.run_doctor("documento-generico-doc", raw)

    names = {c.name for c in result.checks}
    assert "extracted_dir_traceability_only" not in names


def test_run_doctor_result_passed_reflects_rules_config_failure(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)
    config["section_contracts"] = {}  # missing contract for "intro" -> rules_config fails

    result = service.run_doctor("doc1", config)

    assert result.passed is False


# --- Fail-open doctor: manual_dir is optional (item E) ----------------------


def test_run_doctor_manual_dir_missing_warns_not_fails(tmp_path):
    service = _service(tmp_path)
    config = _rules_config_passing_config(tmp_path, manual_dir=str(tmp_path / "missing_manual"))

    result = service.run_doctor("doc1", config)

    manual_check = next(c for c in result.checks if c.name == "manual_dir")
    assert manual_check.ok is False
    assert manual_check.required is False
    assert result.passed is True


def test_run_doctor_manual_check_appears_even_when_manual_dir_not_declared(tmp_path):
    (tmp_path / "inbox").mkdir()
    service = _service(tmp_path)
    config = _config(tmp_path, inbox_dir=str(tmp_path / "inbox"))

    result = service.run_doctor("doc1", config)

    manual_check = next(c for c in result.checks if c.name == "manual_dir")
    assert manual_check.ok is False
    assert manual_check.required is False


def test_run_doctor_manual_dir_required_only_when_strict(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path, manual_dir=str(tmp_path / "missing_manual"))

    non_strict = service.run_doctor("doc1", config, strict=False)
    strict = service.run_doctor("doc1", config, strict=True)

    assert next(c for c in non_strict.checks if c.name == "manual_dir").required is False
    assert next(c for c in strict.checks if c.name == "manual_dir").required is True
    assert strict.passed is False


def test_run_doctor_declared_manual_dir_that_exists_is_ok(tmp_path):
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    service = _service(tmp_path)
    config = _config(tmp_path, manual_dir=str(manual_dir))

    result = service.run_doctor("doc1", config)

    manual_check = next(c for c in result.checks if c.name == "manual_dir")
    assert manual_check.ok is True
    assert manual_check.required is False


def test_run_doctor_auto_detects_manual_by_content_anywhere_under_inbox(tmp_path):
    # spec: document-pipeline "Manual detected anywhere under inbox" -- no
    # hardcoded `{inbox}/guides/manual-estadia-tic` path (design.md item E).
    inbox = tmp_path / "inbox"
    nested = inbox / "random" / "deep"
    nested.mkdir(parents=True)
    manual_file = nested / "normativa-institucional.pdf"
    manual_file.write_bytes(b"%PDF-1.4 fake")
    service = _service(tmp_path)
    config = _config(tmp_path, inbox_dir=str(inbox))

    result = service.run_doctor("doc1", config)

    manual_check = next(c for c in result.checks if c.name == "manual_dir")
    assert manual_check.ok is True
    assert manual_check.required is False
    assert "normativa-institucional.pdf" in manual_check.detail


def test_run_doctor_does_not_auto_detect_a_non_manual_file_under_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "photo.png").write_bytes(b"stub")
    service = _service(tmp_path)
    config = _config(tmp_path, inbox_dir=str(inbox))

    result = service.run_doctor("doc1", config)

    manual_check = next(c for c in result.checks if c.name == "manual_dir")
    assert manual_check.ok is False


# --- Toolchain validation + optional capabilities (item L) -----------------


def test_run_doctor_pandoc_missing_fails_as_required(tmp_path):
    class _NoToolsResolver:
        def resolve_pandoc(self, paths):
            return None

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _NoToolsResolver())
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    pandoc_check = next(c for c in result.checks if c.name == "pandoc")
    assert pandoc_check.ok is False
    assert pandoc_check.required is True
    assert result.passed is False


def test_run_doctor_uv_check_is_always_required(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    uv_check = next(c for c in result.checks if c.name == "uv")
    assert uv_check.required is True


def test_run_doctor_pdf_page_render_capability_warns_when_pypdfium2_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    service = _service(tmp_path)
    config = _rules_config_passing_config(tmp_path)

    result = service.run_doctor("doc1", config)

    check = next(c for c in result.checks if c.name == "pdf_page_render")
    assert check.ok is False
    assert check.required is False
    assert result.passed is True


def test_run_doctor_pdf_raster_extract_capability_warns_when_opendataloader_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "opendataloader_pdf", None)
    service = _service(tmp_path)
    config = _rules_config_passing_config(tmp_path)

    result = service.run_doctor("doc1", config)

    check = next(c for c in result.checks if c.name == "pdf_raster_extract")
    assert check.ok is False
    assert check.required is False
    assert result.passed is True


def test_run_doctor_java_capability_check_is_optional(tmp_path):
    class _NoJavaResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _NoJavaResolver())
    config = _rules_config_passing_config(tmp_path)

    result = service.run_doctor("doc1", config)

    java_check = next(c for c in result.checks if c.name == "java")
    assert java_check.ok is False
    assert java_check.required is False
    assert result.passed is True
