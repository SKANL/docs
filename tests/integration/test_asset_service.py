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


@pytest.fixture
def single_pdf_kind_service(workspace: Workspace) -> AssetService:
    return AssetService(
        FilesystemAssetRepository(),
        workspace,
        asset_kinds={"pdf": (".pdf",)},
    )


@pytest.fixture
def overlapping_docx_kinds_service(workspace: Workspace) -> AssetService:
    return AssetService(
        FilesystemAssetRepository(),
        workspace,
        asset_kinds={"word": (".docx",), "plantilla": (".docx",)},
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
    with pytest.raises(ValueError, match="más de un tipo configurado"):
        multi_kind_service.remove_asset("doc-1", "portada")
    # Ambiguous resolution must not delete anything.
    assert sorted(multi_kind_service.list_assets("doc-1", kind="docx") + multi_kind_service.list_assets("doc-1", kind="pdf")) == [
        "portada",
        "portada",
    ]


def test_remove_asset_raises_when_bare_stem_not_found_under_multiple_kinds(multi_kind_service):
    with pytest.raises(ValueError, match="No se encontró el asset"):
        multi_kind_service.remove_asset("doc-1", "no-existe")


def test_remove_asset_resolves_bare_stem_when_only_kind_configured_is_non_docx(
    tmp_path, workspace, single_pdf_kind_service
):
    # Regression for CRITICAL finding: a single non-docx configured kind must resolve
    # the bare stem to that kind's own extension, not fall through to asset_path's
    # hardcoded ".docx" default (which silently no-ops the removal).
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"pdf-bytes")
    single_pdf_kind_service.add_asset("doc-1", str(source), name="portada")
    single_pdf_kind_service.remove_asset("doc-1", "portada")
    assert single_pdf_kind_service.list_assets("doc-1", kind="pdf") == []


def test_remove_asset_dedupes_matches_when_kinds_overlap_same_extension(
    tmp_path, workspace, overlapping_docx_kinds_service
):
    # Regression for WARNING finding: two configured kinds sharing the same extension
    # must not double-count a single real file as an ambiguous match.
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    overlapping_docx_kinds_service.add_asset("doc-1", str(source), name="unico")
    overlapping_docx_kinds_service.remove_asset("doc-1", "unico")
    assert overlapping_docx_kinds_service.list_assets("doc-1", kind="word") == []


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


def test_remove_asset_stem_matching_finds_asset_regardless_of_case(tmp_path, workspace, multi_kind_service):
    # D3 (tech-debt closeout): on Windows, `asset_path`'s direct suffixed lookup
    # resolves case-insensitively via the OS filesystem, but stem-matching in
    # `_resolve_ambiguous_stem` used to compare names case-sensitively in
    # Python -- so the same logical asset resolved differently depending on
    # which path handled it. Stem matching must casefold before comparing.
    assets_dir = workspace.assets_dir("doc-1")
    assets_dir.mkdir(parents=True)
    (assets_dir / "Logo.docx").write_bytes(b"x")

    multi_kind_service.remove_asset("doc-1", "logo")

    assert not (assets_dir / "Logo.docx").exists()


class _CaseCollisionRepository:
    """Fake `AssetRepository` returning two paths whose stems differ only by
    case -- simulates a case-sensitive filesystem where both `Portada.docx`
    and `portada.docx` genuinely coexist (impossible to create directly on
    Windows' case-insensitive filesystem)."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths = paths

    def file_exists(self, path: Path) -> bool:
        return True

    def list_assets(self, directory: Path, extensions: tuple[str, ...]) -> list[Path]:
        return [p for p in self._paths if p.suffix in extensions]

    def remove_file(self, path: Path) -> None:  # pragma: no cover - must not be reached
        raise AssertionError("remove_file must not be called for an ambiguous match")


def test_remove_asset_treats_case_only_stem_collision_as_ambiguous(tmp_path, workspace):
    # D3: after casefold-normalizing stem matching, two files differing only
    # by case must surface as an ambiguous match rather than one silently
    # shadowing the other.
    assets_dir = workspace.assets_dir("doc-1")
    paths = [assets_dir / "Portada.docx", assets_dir / "portada.docx"]
    repo = _CaseCollisionRepository(paths)
    service = AssetService(repo, workspace, asset_kinds={"docx": (".docx",), "pdf": (".pdf",)})

    with pytest.raises(ValueError, match="más de un tipo configurado"):
        service.remove_asset("doc-1", "portada")
