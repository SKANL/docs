# tests/unit/infrastructure/test_filesystem_asset_repository.py
from pathlib import Path

from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


def test_ensure_dir_creates_nested_directories(tmp_path: Path):
    repo = FilesystemAssetRepository()
    target = tmp_path / "a" / "b" / "c"
    repo.ensure_dir(target)
    assert target.is_dir()


def test_ensure_dir_is_noop_when_already_exists(tmp_path: Path):
    repo = FilesystemAssetRepository()
    repo.ensure_dir(tmp_path)
    repo.ensure_dir(tmp_path)  # must not raise
    assert tmp_path.is_dir()


def test_copy_file_copies_bytes_and_metadata(tmp_path: Path):
    repo = FilesystemAssetRepository()
    src = tmp_path / "source.docx"
    src.write_bytes(b"docx-bytes")
    dest = tmp_path / "dest.docx"
    repo.copy_file(src, dest)
    assert dest.read_bytes() == b"docx-bytes"


def test_list_assets_returns_sorted_files_matching_kind(tmp_path: Path):
    repo = FilesystemAssetRepository()
    (tmp_path / "b.docx").write_bytes(b"")
    (tmp_path / "a.docx").write_bytes(b"")
    (tmp_path / "c.txt").write_bytes(b"")
    assert [p.name for p in repo.list_assets(tmp_path, (".docx",))] == ["a.docx", "b.docx"]


def test_list_assets_docx_only_config_still_rejects_non_docx(tmp_path: Path):
    repo = FilesystemAssetRepository()
    (tmp_path / "a.docx").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"")
    assert [p.name for p in repo.list_assets(tmp_path, (".docx",))] == ["a.docx"]


def test_list_assets_generalizes_to_other_configured_kinds(tmp_path: Path):
    repo = FilesystemAssetRepository()
    (tmp_path / "a.docx").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"")
    assert [p.name for p in repo.list_assets(tmp_path, (".pdf",))] == ["b.pdf"]


def test_list_assets_returns_empty_list_when_no_file_matches_kind(tmp_path: Path):
    repo = FilesystemAssetRepository()
    (tmp_path / "a.docx").write_bytes(b"")
    assert repo.list_assets(tmp_path, (".pdf",)) == []


def test_list_assets_matches_kind_with_multiple_extensions_regardless_of_kind_name(tmp_path: Path):
    # A kind whose configured extensions do not equal the kind name (e.g. "image" -> .jpg/.jpeg)
    # must still be listable — the glob must not treat the kind name as a literal extension.
    repo = FilesystemAssetRepository()
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "b.jpeg").write_bytes(b"")
    (tmp_path / "c.docx").write_bytes(b"")
    assert [p.name for p in repo.list_assets(tmp_path, (".jpg", ".jpeg"))] == ["a.jpg", "b.jpeg"]


def test_remove_file_is_noop_when_absent(tmp_path: Path):
    repo = FilesystemAssetRepository()
    repo.remove_file(tmp_path / "missing.docx")  # must not raise


def test_remove_file_deletes_existing_file(tmp_path: Path):
    repo = FilesystemAssetRepository()
    path = tmp_path / "x.docx"
    path.write_bytes(b"")
    repo.remove_file(path)
    assert not path.exists()


def test_is_file_false_for_directory(tmp_path: Path):
    repo = FilesystemAssetRepository()
    assert repo.is_file(tmp_path) is False


def test_is_file_true_for_existing_file(tmp_path: Path):
    repo = FilesystemAssetRepository()
    path = tmp_path / "x.docx"
    path.write_bytes(b"")
    assert repo.is_file(path) is True


def test_file_exists_true_for_existing_file(tmp_path: Path):
    repo = FilesystemAssetRepository()
    path = tmp_path / "x.docx"
    path.write_bytes(b"")
    assert repo.file_exists(path) is True


def test_file_exists_false_for_missing_file(tmp_path: Path):
    repo = FilesystemAssetRepository()
    assert repo.file_exists(tmp_path / "missing.docx") is False
