# tests/integration/test_asset_service.py
from pathlib import Path

import pytest

from docs.application.asset import AssetService
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> AssetService:
    return AssetService(FilesystemAssetRepository(), workspace)


@pytest.fixture
def multi_kind_service(workspace: Workspace) -> AssetService:
    return AssetService(
        FilesystemAssetRepository(),
        workspace,
        asset_kinds={"docx": (".docx",), "pdf": (".pdf",)},
    )


def test_add_asset_copies_file_and_appends_docx_suffix(tmp_path, workspace, service):
    source = tmp_path / "cover.docx"
    source.write_bytes(b"docx-bytes")
    target = service.add_asset("doc-1", str(source), name="portada")
    assert target == workspace.assets_dir("doc-1") / "portada.docx"
    assert target.read_bytes() == b"docx-bytes"


def test_add_asset_defaults_name_to_source_stem(tmp_path, workspace, service):
    source = tmp_path / "anexo-a.docx"
    source.write_bytes(b"x")
    target = service.add_asset("doc-1", str(source))
    assert target.name == "anexo-a.docx"


def test_add_asset_does_not_append_docx_twice_when_name_already_has_suffix(tmp_path, workspace, service):
    source = tmp_path / "cover.docx"
    source.write_bytes(b"x")
    target = service.add_asset("doc-1", str(source), name="portada.docx")
    assert target.name == "portada.docx"


def test_add_asset_raises_when_source_missing(tmp_path, service):
    with pytest.raises(FileNotFoundError):
        service.add_asset("doc-1", str(tmp_path / "missing.docx"))


def test_add_asset_raises_when_source_is_not_docx(tmp_path, service):
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        service.add_asset("doc-1", str(source))


def test_add_asset_does_not_copy_when_source_missing(tmp_path, workspace, service):
    with pytest.raises(FileNotFoundError):
        service.add_asset("doc-1", str(tmp_path / "missing.docx"))
    assert not workspace.assets_dir("doc-1").exists()


def test_add_asset_does_not_copy_when_source_is_not_docx(tmp_path, workspace, service):
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        service.add_asset("doc-1", str(source))
    assert not workspace.assets_dir("doc-1").exists()


def test_list_assets_returns_empty_list_when_directory_absent(service):
    assert service.list_assets("doc-1") == []


def test_list_assets_returns_stems_sorted(tmp_path, workspace, service):
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    service.add_asset("doc-1", str(source), name="b-anexo")
    service.add_asset("doc-1", str(source), name="a-portada")
    assert service.list_assets("doc-1") == ["a-portada", "b-anexo"]


def test_remove_asset_deletes_existing_asset(tmp_path, workspace, service):
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    service.add_asset("doc-1", str(source), name="portada")
    service.remove_asset("doc-1", "portada")
    assert service.list_assets("doc-1") == []


def test_remove_asset_is_noop_when_asset_absent(service):
    service.remove_asset("doc-1", "no-existe")  # must not raise


def test_add_asset_list_remove_round_trip(tmp_path, service):
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    service.add_asset("doc-1", str(source), name="portada")
    assert service.list_assets("doc-1") == ["portada"]
    service.remove_asset("doc-1", "portada")
    assert service.list_assets("doc-1") == []


def test_add_asset_stores_configured_non_docx_kind_with_its_own_suffix(tmp_path, workspace, multi_kind_service):
    # A multi-kind config must derive the stored suffix from the source's actual kind,
    # not hardcode ".docx" — otherwise PDF bytes end up mislabeled as a .docx file.
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"pdf-bytes")
    target = multi_kind_service.add_asset("doc-1", str(source), name="portada")
    assert target == workspace.assets_dir("doc-1") / "portada.pdf"
    assert target.read_bytes() == b"pdf-bytes"


def test_list_assets_returns_files_for_configured_pdf_kind(tmp_path, multi_kind_service):
    docx_source = tmp_path / "src.docx"
    docx_source.write_bytes(b"x")
    pdf_source = tmp_path / "cover.pdf"
    pdf_source.write_bytes(b"y")
    multi_kind_service.add_asset("doc-1", str(docx_source), name="anexo")
    multi_kind_service.add_asset("doc-1", str(pdf_source), name="portada")
    assert multi_kind_service.list_assets("doc-1", kind="pdf") == ["portada"]


def test_add_asset_docx_only_config_still_rejects_non_docx_with_configured_kinds(tmp_path, service):
    # Regression guard: the docx-only default config must keep rejecting non-docx sources
    # after generalizing suffix derivation to other kinds.
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        service.add_asset("doc-1", str(source))


def test_remove_asset_resolves_bare_stem_to_only_configured_non_docx_kind(tmp_path, workspace, multi_kind_service):
    # A multi-kind config with a single existing match for the stem must resolve to
    # that match, not silently append ".docx" (the pre-fix behavior).
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"pdf-bytes")
    multi_kind_service.add_asset("doc-1", str(source), name="portada")
    multi_kind_service.remove_asset("doc-1", "portada")
    assert multi_kind_service.list_assets("doc-1", kind="pdf") == []
    assert not (workspace.assets_dir("doc-1") / "portada.docx").exists()


def test_remove_asset_raises_when_bare_stem_ambiguous_across_multiple_kinds(tmp_path, workspace, multi_kind_service):
    docx_source = tmp_path / "src.docx"
    docx_source.write_bytes(b"x")
    pdf_source = tmp_path / "cover.pdf"
    pdf_source.write_bytes(b"y")
    multi_kind_service.add_asset("doc-1", str(docx_source), name="portada")
    multi_kind_service.add_asset("doc-1", str(pdf_source), name="portada")
    with pytest.raises(ValueError):
        multi_kind_service.remove_asset("doc-1", "portada")
    # Ambiguous resolution must not delete anything.
    assert sorted(multi_kind_service.list_assets("doc-1", kind="docx") + multi_kind_service.list_assets("doc-1", kind="pdf")) == [
        "portada",
        "portada",
    ]


def test_remove_asset_raises_when_bare_stem_not_found_under_multiple_kinds(multi_kind_service):
    with pytest.raises(ValueError):
        multi_kind_service.remove_asset("doc-1", "no-existe")


def test_remove_asset_deletes_with_explicit_extension_under_multiple_kinds(tmp_path, workspace, multi_kind_service):
    docx_source = tmp_path / "src.docx"
    docx_source.write_bytes(b"x")
    pdf_source = tmp_path / "cover.pdf"
    pdf_source.write_bytes(b"y")
    multi_kind_service.add_asset("doc-1", str(docx_source), name="portada")
    multi_kind_service.add_asset("doc-1", str(pdf_source), name="portada")
    multi_kind_service.remove_asset("doc-1", "portada.pdf")
    assert multi_kind_service.list_assets("doc-1", kind="pdf") == []
    assert multi_kind_service.list_assets("doc-1", kind="docx") == ["portada"]
