from pathlib import Path
from types import SimpleNamespace

from docs.application.document_input_stages import DocumentInputStageService


def test_resolution_stages_update_document_context_and_validate_renderer_contract():
    resolved = SimpleNamespace(doc_id="report", template=SimpleNamespace(type="academic"), config={"output": {}})
    state = {"resolved": resolved, "config": {"output": {"format": "html"}}, "renderer": SimpleNamespace(output_format="html")}
    service = DocumentInputStageService(
        document_id="report", document_root=Path("/workspace/report"), output_format="html",
        state=state, resolve_context=lambda: resolved, resolve_renderer=lambda config: state["renderer"],
    )

    assert service.resolve_config() == (True, "document=report")
    assert service.resolve_template() == (True, "template=academic")
    assert service.resolve_context_stage() == (True, "document=report")
    assert service.validate_contracts() == (True, "document=report")


def test_contract_stage_reports_format_mismatch():
    state = {"resolved": SimpleNamespace(doc_id="report"), "renderer": SimpleNamespace(output_format="docx")}
    service = DocumentInputStageService(
        document_id="report", document_root=Path("."), output_format="html", state=state,
        resolve_context=lambda: state["resolved"], resolve_renderer=lambda _config: state["renderer"],
    )
    assert service.validate_contracts() == (False, "renderer does not provide html output")


def test_assets_stage_reconstructs_missing_catalog_from_existing_authored_assets(tmp_path):
    sections = tmp_path / "sections"
    figures = tmp_path / "assets" / "figures"
    sections.mkdir()
    figures.mkdir(parents=True)
    (sections / "figure-bindings.json").write_text("{}", encoding="utf-8")
    (figures / "architecture.svg").write_text("<svg/>", encoding="utf-8")
    calls = []
    pipeline = SimpleNamespace(build_figure_catalog_for=lambda *args, **kwargs: calls.append((args, kwargs)))
    state = {"config": {"paths": {"sections_dir": str(sections), "assets_dir": str(tmp_path / "assets")}}}
    service = DocumentInputStageService(
        document_id="report", document_root=tmp_path, output_format="docx", state=state,
        resolve_context=lambda: None, resolve_renderer=lambda _config: None, figure_pipeline=pipeline,
    )

    assert service.resolve_assets() == (True, "catalogued 1 existing figure assets")
    assert len(calls) == 1
    assert calls[0][0][2] == [(figures / "architecture.svg", "assets/figures/architecture.svg")]


def test_source_stage_uses_pipeline_contract_and_preserves_missing_service_message(tmp_path):
    calls = []
    pipeline = SimpleNamespace(run_stage=lambda *args: calls.append(args) or (True, "ingested"))
    state = {"config": {}}
    service = DocumentInputStageService(
        document_id="report", document_root=tmp_path, output_format="docx", state=state,
        resolve_context=lambda: None, resolve_renderer=lambda _config: None, source_pipeline=pipeline,
    )

    assert service.source_stage("ingest-sources") == (True, "ingested")
    assert calls == [("ingest-sources", "report", tmp_path, {})]
    service_without_pipeline = DocumentInputStageService(
        document_id="report", document_root=tmp_path, output_format="docx", state=state,
        resolve_context=lambda: None, resolve_renderer=lambda _config: None,
    )
    assert service_without_pipeline.source_stage("ingest-sources") == (False, "ingest-sources service is not configured")
