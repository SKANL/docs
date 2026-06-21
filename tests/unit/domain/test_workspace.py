from pathlib import Path
from docs.domain.workspace import Workspace
from docs.domain.models.document import Document


def test_workspace_derives_registry_and_doc_root():
    ws = Workspace(documents_dir=Path("/w/documents"), templates_dir=Path("/w/templates"))
    assert ws.registry_path == Path("/w/documents/registry.json")
    assert ws.doc_root("alpha") == Path("/w/documents/alpha")


def test_assets_dir_is_under_doc_root(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    assert workspace.assets_dir("doc-1") == workspace.doc_root("doc-1") / "assets"


def test_document_to_json_is_sorted_and_unicode():
    doc = Document(id="a", title="Área", template="documento-generico")
    text = doc.to_json()
    assert text.index('"id"') < text.index('"title"')  # sort_keys
    assert "Área" in text  # ensure_ascii=False
