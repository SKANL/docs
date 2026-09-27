import pytest

from docs.domain.models.document import Document
from docs.domain.workspace import Workspace
from docs.domain.workspace_format import WorkspaceFormatError


def test_workspace_derives_registry_and_doc_root(tmp_path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    assert ws.registry_path == (tmp_path / "documents" / "registry.json").resolve()
    assert ws.doc_root("alpha") == (tmp_path / "documents" / "alpha").resolve()


def test_assets_dir_is_under_doc_root(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    assert workspace.assets_dir("doc-1") == workspace.doc_root("doc-1") / "assets"


def test_workspace_retains_explicit_canonical_root(tmp_path):
    workspace = Workspace(
        root=tmp_path,
        documents_dir=tmp_path / "content" / "documents",
        templates_dir=tmp_path / "shared" / "templates",
    )

    assert workspace.root == tmp_path.resolve()
    assert workspace.documents_dir == (tmp_path / "content" / "documents").resolve()
    assert workspace.templates_dir == (tmp_path / "shared" / "templates").resolve()


def test_workspace_rejects_content_root_outside_explicit_root(tmp_path):
    with pytest.raises(WorkspaceFormatError, match="workspace_path_outside_root"):
        Workspace(
            root=tmp_path / "workspace",
            documents_dir=tmp_path / "outside-documents",
            templates_dir=tmp_path / "workspace" / "templates",
        )


def test_workspace_does_not_infer_root_for_split_legacy_layout(tmp_path):
    with pytest.raises(ValueError, match="workspace_root_required"):
        Workspace(
            documents_dir=tmp_path / "documents-root" / "documents",
            templates_dir=tmp_path / "templates-root" / "templates",
        )


def test_document_to_json_is_sorted_and_unicode():
    doc = Document(id="a", title="Área", template="documento-generico")
    text = doc.to_json()
    assert text.index('"id"') < text.index('"title"')  # sort_keys
    assert "Área" in text  # ensure_ascii=False
