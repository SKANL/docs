# tests/unit/domain/test_repository_ports.py
"""RED (task 2.1): the fat `DocumentRepository` port must be segregated into
three narrow, independently-usable ports: `RegistryRepository`,
`DocumentRepository` (content), and `TemplateRepository`.

Each fake below implements the method surface of exactly ONE narrow port and
must satisfy isinstance-checks (structural typing, via `runtime_checkable`)
for that port only — proving the ports are genuinely segregated, not just
aliases of the same fat interface.
"""
from __future__ import annotations

from docs.domain.ports.document_repository import DocumentRepository
from docs.domain.ports.registry_repository import RegistryRepository
from docs.domain.ports.template_repository import TemplateRepository


class FakeRegistryOnly:
    def load_registry(self): ...
    def save_registry(self, registry): ...
    def active_id(self) -> str:
        return ""
    def set_active(self, doc_id: str) -> None: ...
    def register(self, summary) -> None: ...


class FakeDocumentOnly:
    def read_document(self, doc_id: str): ...
    def write_document(self, document) -> None: ...
    def exists(self, doc_id: str) -> bool:
        return False
    def move(self, old_id: str, new_id: str) -> None: ...
    def remove(self, doc_id: str) -> None: ...


class FakeTemplateOnly:
    def load_template(self, name: str): ...
    def list_templates(self) -> list[str]:
        return []


def test_registry_repository_usable_independently():
    fake = FakeRegistryOnly()
    assert isinstance(fake, RegistryRepository)
    assert not isinstance(fake, DocumentRepository)
    assert not isinstance(fake, TemplateRepository)


def test_document_repository_usable_independently():
    fake = FakeDocumentOnly()
    assert isinstance(fake, DocumentRepository)
    assert not isinstance(fake, RegistryRepository)
    assert not isinstance(fake, TemplateRepository)


def test_template_repository_usable_independently():
    fake = FakeTemplateOnly()
    assert isinstance(fake, TemplateRepository)
    assert not isinstance(fake, RegistryRepository)
    assert not isinstance(fake, DocumentRepository)
