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
