# tests/unit/application/test_asset_service.py
"""Unit coverage for AssetService (document-pipeline spec: `Application-Layer
Test Coverage`). Uses lightweight fakes for AssetRepository/Workspace instead
of real filesystem adapters -- exercises the service's own validation logic
in isolation (see tests/integration/test_asset_service.py for the
repository-backed integration coverage of this same service)."""
from __future__ import annotations

from pathlib import Path

import pytest

from docs.application.asset import AssetService


class _FakeAssetRepository:
    def file_exists(self, path: Path) -> bool:
        return False

    def list_assets(self, directory: Path, extensions):
        return []

    def is_file(self, path: Path) -> bool:
        return False

    def ensure_dir(self, path: Path) -> None:
        pass

    def copy_file(self, src: Path, dst: Path) -> None:
        pass

    def remove_file(self, path: Path) -> None:
        pass


class _FakeWorkspace:
    def assets_dir(self, doc_id: str) -> Path:
        return Path("fake-doc-root") / doc_id / "assets"


def test_list_assets_raises_for_a_kind_not_in_the_configured_map():
    class _RepoWithAssetsDir(_FakeAssetRepository):
        def file_exists(self, path: Path) -> bool:
            return True  # assets dir "exists" so the kind lookup is reached

    service = AssetService(_RepoWithAssetsDir(), _FakeWorkspace(), asset_kinds={"docx": (".docx",)})

    with pytest.raises(ValueError, match="no configurado"):
        service.list_assets("doc1", kind="pdf")


def test_asset_path_keeps_a_name_that_already_has_a_known_extension():
    service = AssetService(_FakeAssetRepository(), _FakeWorkspace(), asset_kinds={"pdf": (".pdf",)})

    path = service.asset_path("doc1", "cover.pdf")

    assert path.name == "cover.pdf"


def test_add_asset_rejects_an_extension_outside_the_configured_kinds(tmp_path):
    source = tmp_path / "cover.png"
    source.write_bytes(b"not really a docx")

    class _RepoWithRealFile(_FakeAssetRepository):
        def is_file(self, path: Path) -> bool:
            return path == source

    service = AssetService(_RepoWithRealFile(), _FakeWorkspace(), asset_kinds={"docx": (".docx",)})

    with pytest.raises(ValueError, match="no permitido"):
        service.add_asset("doc1", str(source))
