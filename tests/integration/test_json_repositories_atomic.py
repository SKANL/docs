"""Every JSON repository publishes through the atomic writer and never resets a corrupt registry."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Topic
from docs.domain.ports.registry_repository import RegistryCorruptError
from docs.domain.workspace import Workspace
from docs.domain.workspace_format import write_workspace_marker
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    write_workspace_marker(tmp_path)
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


def _interrupt_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash before the rename")

    monkeypatch.setattr(os, "replace", boom)


def _assert_untouched(path: Path, original: bytes) -> None:
    assert path.read_bytes() == original
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_registry_write_interrupted_keeps_previous_file(workspace, monkeypatch):
    repo = JsonDocumentRepository(workspace)
    repo.register(DocumentSummary(id="alpha", title="A", template="t", created_at="t"))
    original = workspace.registry_path.read_bytes()
    _interrupt_replace(monkeypatch)
    with pytest.raises(OSError):
        repo.register(DocumentSummary(id="beta", title="B", template="t", created_at="t"))
    _assert_untouched(workspace.registry_path, original)


def test_document_write_interrupted_keeps_previous_file(workspace, monkeypatch):
    repo = JsonDocumentRepository(workspace)
    repo.write_document(Document(id="alpha", title="A", template="t"))
    path = workspace.doc_root("alpha") / "document.json"
    original = path.read_bytes()
    _interrupt_replace(monkeypatch)
    with pytest.raises(OSError):
        repo.write_document(Document(id="alpha", title="Changed", template="t"))
    _assert_untouched(path, original)


def test_section_writes_interrupted_keep_previous_files(workspace, monkeypatch):
    repo = JsonSectionRepository(workspace)
    repo.write_section("d", 1, "intro", "old")
    proposal = repo.write_proposal_section("d", 1, "intro", "old")
    pack = repo.write_context_pack(repo.context_pack_path("d", 1, "intro"), "old")
    raw = repo.section_path("d", 1, "intro")
    before = {p: p.read_bytes() for p in (proposal, pack, raw)}
    _interrupt_replace(monkeypatch)
    with pytest.raises(OSError):
        repo.write_section("d", 1, "intro", "new")
    with pytest.raises(OSError):
        repo.write_proposal_section("d", 1, "intro", "new")
    with pytest.raises(OSError):
        repo.write_context_pack(pack, "new")
    with pytest.raises(OSError):
        repo.write_raw_text(raw, "new")
    for path, original in before.items():
        _assert_untouched(path, original)


def test_context_writes_interrupted_keep_previous_files(workspace, monkeypatch):
    repo = JsonContextRepository(workspace)
    topic = Topic(id="t1", title="T", multiline=True, consumed_by=["s1"])
    schema = ContextSchema(topics=[topic])
    topic_path = repo.write_topic("d", topic, "old")
    repo.write_requests("d", "old")
    index = repo.regenerate_index("d", schema, [])
    targets = [topic_path, repo._requests_path("d"), index, index.with_name("index.md")]
    before = {p: p.read_bytes() for p in targets}
    _interrupt_replace(monkeypatch)
    with pytest.raises(OSError):
        repo.write_topic("d", topic, "new")
    with pytest.raises(OSError):
        repo.write_requests("d", "new")
    with pytest.raises(OSError):
        repo.regenerate_index("d", schema, [])
    for path, original in before.items():
        _assert_untouched(path, original)


def test_manifest_write_interrupted_keeps_previous_file(tmp_path, monkeypatch):
    repo = JsonEvidenceRepository()
    path = tmp_path / "manifest.json"
    repo.write_manifest(path, {"a": 1})
    original = path.read_bytes()
    _interrupt_replace(monkeypatch)
    with pytest.raises(OSError):
        repo.write_manifest(path, {"a": 2})
    _assert_untouched(path, original)


@pytest.mark.parametrize("garbage", [b'{"schema": 1, "documents": [', b"", b"[]"])
def test_corrupt_registry_raises_and_is_never_modified(workspace, garbage):
    workspace.registry_path.parent.mkdir(parents=True)
    workspace.registry_path.write_bytes(garbage)
    repo = JsonDocumentRepository(workspace)
    with pytest.raises(RegistryCorruptError, match=r"registry\.json"):
        repo.load_registry()
    with pytest.raises(RegistryCorruptError):
        repo.register(DocumentSummary(id="x", title="X", template="t", created_at="t"))
    assert workspace.registry_path.read_bytes() == garbage


def test_missing_registry_is_still_empty(workspace):
    registry = JsonDocumentRepository(workspace).load_registry()
    assert registry.documents == [] and registry.active == ""


def test_every_repository_writes_into_a_missing_parent(workspace, tmp_path):
    assert not workspace.documents_dir.exists()
    documents = JsonDocumentRepository(workspace)
    documents.register(DocumentSummary(id="alpha", title="A", template="t", created_at="t"))
    documents.write_document(Document(id="alpha", title="A", template="t"))
    assert workspace.registry_path.is_file()
    assert (workspace.doc_root("alpha") / "document.json").is_file()

    sections = JsonSectionRepository(workspace)
    sections.write_section("d", 1, "intro", "text")
    nested_raw = tmp_path / "no" / "such" / "dir" / "raw.txt"
    sections.write_raw_text(nested_raw, "raw")
    assert nested_raw.read_text(encoding="utf-8") == "raw"

    contexts = JsonContextRepository(workspace)
    topic = Topic(id="t1", title="T", multiline=True, consumed_by=["s1"])
    assert contexts.write_topic("d2", topic, "body").is_file()
    contexts.write_requests("d2", "req")
    assert contexts._requests_path("d2").is_file()

    nested_manifest = tmp_path / "x" / "y" / "manifest.json"
    JsonEvidenceRepository().write_manifest(nested_manifest, {"a": 1})
    assert nested_manifest.is_file()
