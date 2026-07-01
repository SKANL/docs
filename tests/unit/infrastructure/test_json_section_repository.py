from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def repo(workspace: Workspace) -> JsonSectionRepository:
    return JsonSectionRepository(workspace)


def test_section_path_uses_zero_padded_order_and_id(workspace: Workspace, repo: JsonSectionRepository):
    path = repo.section_path("doc-1", 3, "introduccion")
    assert path == workspace.doc_root("doc-1") / "sections" / "003-introduccion.md"


def test_section_path_pads_multi_digit_order(workspace: Workspace, repo: JsonSectionRepository):
    path = repo.section_path("doc-1", 12, "metodologia")
    assert path.name == "012-metodologia.md"


def test_sections_dir_exists_false_when_absent(repo: JsonSectionRepository):
    assert repo.sections_dir_exists("doc-1") is False


def test_sections_dir_exists_true_when_present(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    assert repo.sections_dir_exists("doc-1") is True


def test_section_exists_false_when_file_absent(repo: JsonSectionRepository):
    assert repo.section_exists("doc-1", 1, "introduccion") is False


def test_section_exists_true_when_file_present(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text("# Introducción\n", encoding="utf-8")
    assert repo.section_exists("doc-1", 1, "introduccion") is True


def test_read_section_splits_frontmatter_and_body(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    raw = (
        '---\n{"section_id": "introduccion", "schema": 3}\n---\n'
        "# Introducción\n\nTexto.\n"
    )
    (sections_dir / "001-introduccion.md").write_text(raw, encoding="utf-8")
    metadata, body = repo.read_section("doc-1", 1, "introduccion")
    assert metadata == {"section_id": "introduccion", "schema": 3}
    assert body == "# Introducción\n\nTexto.\n"


def test_read_section_returns_empty_metadata_when_no_frontmatter(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "002-objetivos.md").write_text("# Objetivos\n\nTexto.\n", encoding="utf-8")
    metadata, body = repo.read_section("doc-1", 2, "objetivos")
    assert metadata == {}
    assert body == "# Objetivos\n\nTexto.\n"


def test_read_section_raises_file_not_found_when_missing(repo: JsonSectionRepository):
    with pytest.raises(FileNotFoundError):
        repo.read_section("doc-1", 9, "missing")


def test_write_section_creates_sections_dir_and_writes_file(workspace, repo):
    repo.write_section("doc-1", 1, "introduccion", "---\n{}\n---\n# Introducción\n")
    path = workspace.doc_root("doc-1") / "sections" / "001-introduccion.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "---\n{}\n---\n# Introducción\n"


def test_write_section_overwrites_existing_file(workspace, repo):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    path = sections_dir / "002-objetivos.md"
    path.write_text("vieja version", encoding="utf-8")
    repo.write_section("doc-1", 2, "objetivos", "nueva version")
    assert path.read_text(encoding="utf-8") == "nueva version"


def test_write_section_path_matches_section_path(workspace, repo):
    repo.write_section("doc-1", 3, "metodologia", "contenido")
    expected_path = repo.section_path("doc-1", 3, "metodologia")
    assert expected_path.read_text(encoding="utf-8") == "contenido"


def test_write_proposal_section_creates_proposals_dir_and_writes_file(workspace, repo):
    repo.write_proposal_section("doc-1", 1, "introduccion", "contenido propuesto")
    path = workspace.doc_root("doc-1") / "sections" / "_proposals" / "001-introduccion.candidate.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "contenido propuesto"


def test_write_proposal_section_returns_the_written_path(workspace, repo):
    result = repo.write_proposal_section("doc-1", 1, "introduccion", "contenido propuesto")
    expected_path = workspace.doc_root("doc-1") / "sections" / "_proposals" / "001-introduccion.candidate.md"
    assert result == expected_path


def test_context_pack_path_under_context_subdir(workspace, repo):
    path = repo.context_pack_path("doc-1", 3, "introduccion")
    expected_path = workspace.doc_root("doc-1") / "sections" / "_context" / "003-introduccion.context.md"
    assert path == expected_path
    assert path.name == "003-introduccion.context.md"
    assert path.parent.name == "_context"


def test_context_pack_path_pads_multi_digit_order(workspace, repo):
    path = repo.context_pack_path("doc-1", 12, "metodologia")
    assert path.name == "012-metodologia.context.md"


def test_document_context_pack_path_is_000_document(workspace, repo):
    path = repo.document_context_pack_path("doc-1")
    expected_path = workspace.doc_root("doc-1") / "sections" / "_context" / "000-document.context.md"
    assert path == expected_path
    assert path.name == "000-document.context.md"


def test_write_context_pack_creates_dir_and_writes_content(workspace, repo):
    target = repo.context_pack_path("doc-1", 1, "introduccion")
    result = repo.write_context_pack(target, "contenido")
    assert result == target
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "contenido"


def test_write_context_pack_overwrites_existing_file(workspace, repo):
    target = repo.context_pack_path("doc-1", 1, "introduccion")
    target.parent.mkdir(parents=True)
    target.write_text("vieja version", encoding="utf-8")
    repo.write_context_pack(target, "nueva version")
    assert target.read_text(encoding="utf-8") == "nueva version"


def test_write_document_context_pack_path_works_too(workspace, repo):
    target = repo.document_context_pack_path("doc-1")
    result = repo.write_context_pack(target, "resumen global")
    assert result == target
    assert target.read_text(encoding="utf-8") == "resumen global"


def test_find_section_file_returns_the_matching_path(repo: JsonSectionRepository):
    repo.write_section("doc1", 2, "intro", "body")
    found = repo.find_section_file("doc1", "intro")
    assert found == repo.section_path("doc1", 2, "intro")


def test_find_section_file_returns_none_when_nothing_matches(repo: JsonSectionRepository):
    assert repo.find_section_file("doc1", "missing") is None


def test_find_section_file_returns_the_first_sorted_match_when_multiple_exist(repo: JsonSectionRepository):
    repo.write_section("doc1", 2, "intro", "second")
    repo.write_section("doc1", 1, "intro", "first")
    found = repo.find_section_file("doc1", "intro")
    assert found == repo.section_path("doc1", 1, "intro")


def test_read_raw_text_returns_the_full_file_content_including_frontmatter(repo: JsonSectionRepository):
    repo.write_section("doc1", 1, "intro", "---\nsection_id: intro\n---\nBody text")
    path = repo.section_path("doc1", 1, "intro")
    assert repo.read_raw_text(path) == "---\nsection_id: intro\n---\nBody text"


def test_write_raw_text_creates_parent_directories_and_writes_content(repo: JsonSectionRepository, tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "file.md"
    repo.write_raw_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"
