# tests/integration/test_deps_ingest_wiring.py
"""Composition-root wiring for the PR6 ingest adapters (document-ingest
spec: `Type-Based Ingest Routing`) — `Deps.ingest` must route every
supported kind to a real adapter, not just the PR5 routing stubs."""
from pathlib import Path

from docs.application.ingest import IngestService
from docs.cli._shared import Deps
from docs.domain.workspace import Workspace
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.ingest.opendataloader_pdf_adapter import OpendataloaderPdfAdapter
from docs.infrastructure.ingest.pandoc_ingest_adapter import PandocIngestAdapter


def _deps(tmp_path: Path) -> Deps:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return Deps(workspace)


def test_deps_builds_an_ingest_service(tmp_path: Path):
    deps = _deps(tmp_path)
    assert isinstance(deps.ingest, IngestService)


def test_deps_registers_a_handler_for_every_supported_kind(tmp_path: Path):
    deps = _deps(tmp_path)
    assert set(deps.ingest.handlers) == {"docx", "odt", "pdf", "md", "txt"}


def test_deps_routes_docx_and_odt_to_the_same_pandoc_adapter_instance(tmp_path: Path):
    deps = _deps(tmp_path)
    assert isinstance(deps.ingest.handlers["docx"], PandocIngestAdapter)
    assert deps.ingest.handlers["docx"] is deps.ingest.handlers["odt"]


def test_deps_routes_pdf_to_opendataloader_pdf_adapter(tmp_path: Path):
    deps = _deps(tmp_path)
    assert isinstance(deps.ingest.handlers["pdf"], OpendataloaderPdfAdapter)


def test_deps_routes_md_and_txt_to_the_same_normalize_adapter_instance(tmp_path: Path):
    deps = _deps(tmp_path)
    assert isinstance(deps.ingest.handlers["md"], MdNormalizeAdapter)
    assert deps.ingest.handlers["md"] is deps.ingest.handlers["txt"]
