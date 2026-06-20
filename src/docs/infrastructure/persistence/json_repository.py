from __future__ import annotations

from pathlib import Path

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import Template
from docs.domain.ports.document_repository import (
    DocumentExistsError, DocumentNotFoundError, Registry,
)
from docs.domain.workspace import Workspace


class JsonDocumentRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    # registry -----------------------------------------------------------------
    def load_registry(self) -> Registry:
        path = self.workspace.registry_path
        if path.exists():
            try:
                return Registry.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return Registry()

    def save_registry(self, registry: Registry) -> None:
        path = self.workspace.registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(registry.to_json(), encoding="utf-8")

    def active_id(self) -> str:
        return self.load_registry().active

    def set_active(self, doc_id: str) -> None:
        registry = self.load_registry()
        if doc_id and doc_id not in {d.id for d in registry.documents}:
            raise DocumentNotFoundError(f"Unknown document: {doc_id}.")
        registry.active = doc_id
        self.save_registry(registry)

    def register(self, summary: DocumentSummary) -> None:
        registry = self.load_registry()
        documents = [d for d in registry.documents if d.id != summary.id]
        documents.append(summary)
        registry.documents = sorted(documents, key=lambda d: d.id)
        registry.active = summary.id
        self.save_registry(registry)

    # documents ----------------------------------------------------------------
    def _document_json(self, doc_id: str) -> Path:
        return self.workspace.doc_root(doc_id) / "document.json"

    def exists(self, doc_id: str) -> bool:
        return self.workspace.doc_root(doc_id).exists()

    def read_document(self, doc_id: str) -> Document:
        path = self._document_json(doc_id)
        if not path.exists():
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist ({path}).")
        return Document.model_validate_json(path.read_text(encoding="utf-8"))

    def write_document(self, document: Document) -> None:
        path = self._document_json(document.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document.to_json(), encoding="utf-8")

    # templates ----------------------------------------------------------------
    def load_template(self, name: str) -> Template:
        path = self.workspace.templates_dir / f"{name}.json"
        if not path.exists():
            known = ", ".join(self.list_templates()) or "(none)"
            raise FileNotFoundError(f"Unknown template: {name}. Available: {known}")
        return Template.from_json(path.read_text(encoding="utf-8"))

    def list_templates(self) -> list[str]:
        directory = self.workspace.templates_dir
        if not directory.exists():
            return []
        return [p.stem for p in sorted(directory.glob("*.json"))]

    # mutations ------------------------------------------------------------------
    def move(self, old_id: str, new_id: str) -> None:
        src = self.workspace.doc_root(old_id)
        dst = self.workspace.doc_root(new_id)
        if not src.exists():
            raise DocumentNotFoundError(f"Document `{old_id}` does not exist.")
        if dst.exists():
            raise DocumentExistsError(f"Document `{new_id}` already exists.")
        src.rename(dst)
        document = self.read_document(new_id)
        document.id = new_id
        self.write_document(document)
        registry = self.load_registry()
        for summary in registry.documents:
            if summary.id == old_id:
                summary.id = new_id
        if registry.active == old_id:
            registry.active = new_id
        self.save_registry(registry)

    def remove(self, doc_id: str) -> None:
        import shutil

        doc_root = self.workspace.doc_root(doc_id)
        if not doc_root.exists():
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist.")
        if self.workspace.documents_dir.resolve() not in doc_root.resolve().parents:
            raise ValueError(f"Refusing to delete outside workspace: {doc_root}")
        shutil.rmtree(doc_root)
        registry = self.load_registry()
        registry.documents = [d for d in registry.documents if d.id != doc_id]
        if registry.active == doc_id:
            registry.active = registry.documents[0].id if registry.documents else ""
        self.save_registry(registry)
