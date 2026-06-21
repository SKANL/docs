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
