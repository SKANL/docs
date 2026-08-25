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

        def resolve_mmdc(self, paths):
            return None

        def resolve_resvg(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _FakeToolResolver())
    config = _config(tmp_path)

    result = service.run_doctor("doc-1", config)

    pandoc_check = next(c for c in result.checks if c.name == "pandoc")
    libreoffice_check = next(c for c in result.checks if c.name == "libreoffice")
    assert pandoc_check.ok is True
    # The detail now carries the version alongside the path (see
    # `test_doctor_reports_the_pandoc_version_it_found`); this test is about
    # WHICH resolver was consulted, so it asserts the path is present.
    assert "/fake/pandoc" in pandoc_check.detail
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

        def resolve_mmdc(self, paths):
            return None

        def resolve_resvg(self, paths):
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

        def resolve_mmdc(self, paths):
            return None

        def resolve_resvg(self, paths):
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


# --- Slice 7: resvg/mmdc optional capability checks -------------------------


def test_run_doctor_resvg_and_mmdc_capability_checks_required_false_when_absent(tmp_path):
    class _NoVisualToolsResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
            return None

        def resolve_mmdc(self, paths):
            return None

        def resolve_resvg(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _NoVisualToolsResolver())
    config = _rules_config_passing_config(tmp_path)

    result = service.run_doctor("doc1", config)

    mmdc_check = next(c for c in result.checks if c.name == "mmdc")
    resvg_check = next(c for c in result.checks if c.name == "resvg")
    assert mmdc_check.ok is False
    assert mmdc_check.required is False
    assert "mermaid" in mmdc_check.detail.lower()
    assert resvg_check.ok is False
    assert resvg_check.required is False
    assert "resvg" in resvg_check.detail.lower()
    assert result.passed is True


def test_run_doctor_resvg_and_mmdc_capability_checks_ok_when_present(tmp_path):
    class _AllVisualToolsResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
            return None

        def resolve_mmdc(self, paths):
            return "/fake/mmdc"

        def resolve_resvg(self, paths):
            return "/fake/resvg"

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _AllVisualToolsResolver())
    config = _rules_config_passing_config(tmp_path)

    result = service.run_doctor("doc1", config)

    mmdc_check = next(c for c in result.checks if c.name == "mmdc")
    resvg_check = next(c for c in result.checks if c.name == "resvg")
    assert mmdc_check.ok is True
    assert mmdc_check.detail == "/fake/mmdc"
    assert mmdc_check.required is False
    assert resvg_check.ok is True
    assert resvg_check.detail == "/fake/resvg"
    assert resvg_check.required is False


# --- "found" is not "usable": version reporting -------------------------------


def _doctor(tmp_path, resolver):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return DoctorService(
        JsonEvidenceRepository(), AssetService(FilesystemAssetRepository(), workspace), resolver
    )


def _resolver(pandoc="/fake/pandoc", version_text="pandoc 3.10"):
    class _Resolver:
        def resolve_pandoc(self, paths):
            return pandoc

        def resolve_libreoffice(self, paths):
            return None

        def resolve_java(self, paths):
            return None

        def resolve_mmdc(self, paths):
            return None

        def resolve_resvg(self, paths):
            return None

        def tool_version(self, executable):
            return version_text

    return _Resolver()


def test_doctor_reports_the_pandoc_version_it_found(tmp_path):
    result = _doctor(tmp_path, _resolver(version_text="pandoc 3.10")).run_doctor(
        "doc-1", _config(tmp_path)
    )

    pandoc = next(c for c in result.checks if c.name == "pandoc")
    assert "3.10" in pandoc.detail


def test_doctor_warns_when_pandoc_is_older_than_the_harness_needs(tmp_path):
    # `html_render` passes `--embed-resources`, which pandoc added in 2.19.
    # Below that, `--format html` fails with a bare non-zero exit -- the
    # exact shape of failure this check exists to pre-empt.
    result = _doctor(tmp_path, _resolver(version_text="pandoc 2.9.2")).run_doctor(
        "doc-1", _config(tmp_path)
    )

    check = next(c for c in result.checks if c.name == "pandoc_version")
    assert check.ok is False
    assert "2.9.2" in check.detail
    assert "2.19" in check.detail
    assert check.required is False, "una versión vieja degrada html, no bloquea docx"


def test_doctor_passes_the_version_check_on_a_new_enough_pandoc(tmp_path):
    result = _doctor(tmp_path, _resolver(version_text="pandoc 2.19")).run_doctor(
        "doc-1", _config(tmp_path)
    )

    assert next(c for c in result.checks if c.name == "pandoc_version").ok is True


def test_an_unreadable_version_is_never_reported_as_too_old(tmp_path):
    # A tool that does not answer `--version` the expected way may be
    # perfectly fine. Guessing "too old" would send someone to reinstall
    # something that works.
    result = _doctor(tmp_path, _resolver(version_text="???")).run_doctor(
        "doc-1", _config(tmp_path)
    )

    check = next(c for c in result.checks if c.name == "pandoc_version")
    assert check.ok is True
    assert "desconocida" in check.detail


def test_no_version_check_when_the_tool_is_absent(tmp_path):
    result = _doctor(tmp_path, _resolver(pandoc=None)).run_doctor("doc-1", _config(tmp_path))

    assert not any(c.name == "pandoc_version" for c in result.checks)


# --- three findings from rebuilding one real, delivered document --------------


class _Probe:
    """A content probe that reports one path as an unreadable container."""

    def __init__(self, broken: str = "") -> None:
        self.broken = broken

    def probe(self, path):
        from docs.domain.ports.content_probe_port import ContentSignals

        return ContentSignals(
            extension=path.suffix.lower().lstrip("."),
            container_ok=str(path) != self.broken,
        )


def _doctor_with_probe(tmp_path, probe):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return DoctorService(
        JsonEvidenceRepository(),
        AssetService(FilesystemAssetRepository(), workspace),
        _resolver(),
        content_probe=probe,
    )


def test_a_file_that_is_not_really_a_docx_fails_its_check(tmp_path):
    # `template_docx` IS the cover base. Pointing at the wrong file used to
    # pass doctor and die much later inside python-docx, with an error that
    # never names the file the user got wrong.
    fake = tmp_path / "plantilla.docx"
    fake.write_text("no soy un docx", encoding="utf-8")
    service = _doctor_with_probe(tmp_path, _Probe(broken=str(fake)))

    result = service.run_doctor("doc-1", _config(tmp_path, template_docx=str(fake)))

    check = next(c for c in result.checks if c.name == "template_docx")
    assert check.ok is False
    assert "docx" in check.detail.lower()


def test_a_real_docx_still_passes_its_check(tmp_path):
    from docx import Document

    real = tmp_path / "plantilla.docx"
    Document().save(real)
    service = _doctor_with_probe(tmp_path, _Probe())

    result = service.run_doctor("doc-1", _config(tmp_path, template_docx=str(real)))

    assert next(c for c in result.checks if c.name == "template_docx").ok is True


def test_doctor_warns_when_two_drafts_share_the_output_directory(tmp_path):
    # Found in a real workspace: `output/draft/` held `reporte-estadia-draft.docx`
    # next to `tesina-draft.docx`, left behind when the output name changed.
    # Two files called "draft", nothing saying which is current, and the wrong
    # one is one careless copy away from being delivered.
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "informe-draft.docx").write_bytes(b"x")
    (draft / "tesina-draft.docx").write_bytes(b"x")
    service = _doctor_with_probe(tmp_path, _Probe())

    result = service.run_doctor("doc-1", _config(tmp_path, output_draft_dir=str(draft)))

    check = next(c for c in result.checks if c.name == "stale_drafts")
    assert check.ok is False
    assert "tesina-draft.docx" in check.detail
    assert check.required is False, "avisa, nunca borra la salida de alguien"


def test_a_single_draft_is_not_reported(tmp_path):
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "informe-draft.docx").write_bytes(b"x")
    service = _doctor_with_probe(tmp_path, _Probe())

    result = service.run_doctor("doc-1", _config(tmp_path, output_draft_dir=str(draft)))

    assert next(c for c in result.checks if c.name == "stale_drafts").ok is True


def test_doctor_suggests_a_caption_for_a_full_page_image_without_one(tmp_path):
    # Rebuilding a real document showed two full-page inserts falling back to
    # their filename for alt text (`carta-empresarial`, `carta-academica`).
    # Better than the nothing they had, and worse than a sentence the author
    # could write in five seconds.
    config = _config(tmp_path)
    config["structure"] = [{"type": "image_page", "image": "carta.png"}, {"type": "sections"}]
    service = _doctor_with_probe(tmp_path, _Probe())

    result = service.run_doctor("doc-1", config)

    check = next(c for c in result.checks if c.name == "image_page_caption:carta.png")
    assert check.ok is False
    assert "caption" in check.detail
    assert check.required is False


def test_an_accented_filename_stored_decomposed_is_found(tmp_path):
    # The real-workspace bug, end to end: OneDrive stored the guide's name
    # decomposed, the template declares it composed, and doctor reported a
    # file that was right there as missing.
    import unicodedata

    guides = tmp_path / "guides"
    guides.mkdir()
    on_disk = guides / unicodedata.normalize("NFD", "GUÍA DE REFERENCIA.pdf")
    on_disk.write_bytes(b"%PDF-1.4\n")
    declared = str(guides / unicodedata.normalize("NFC", "GUÍA DE REFERENCIA.pdf"))
    assert not Path(declared).exists(), "el fixture debe reproducir el desencuentro"

    service = _doctor_with_probe(tmp_path, _Probe())
    result = service.run_doctor("doc-1", _config(tmp_path, manual_pdf=declared))

    assert next(c for c in result.checks if c.name == "manual_pdf").ok is True
