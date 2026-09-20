from __future__ import annotations

import inspect
from typing import Protocol

from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.document_repository import DocumentRepository
from docs.domain.ports.render_verification_port import RenderVerificationPort
from docs.domain.ports.x20 import (
    X20_PORT_CONTRACT,
    DocumentStore,
    PluginExecutor,
    Renderer,
    Verifier,
)


def test_public_port_contract_is_explicitly_versioned() -> None:
    assert X20_PORT_CONTRACT == "docs.x20/v1"


def test_public_ports_are_protocols() -> None:
    for port in (DocumentStore, Renderer, Verifier, PluginExecutor):
        assert issubclass(port, Protocol)  # type: ignore[arg-type]


def test_document_store_preserves_the_existing_repository_contract() -> None:
    assert issubclass(DocumentStore, DocumentRepository)
    assert {
        "read_document",
        "write_document",
        "exists",
        "move",
        "remove",
    } <= set(DocumentStore.__dict__) | set(DocumentRepository.__dict__)


def test_renderer_and_verifier_preserve_existing_port_contracts() -> None:
    assert DocumentRendererPort in Renderer.__mro__
    assert RenderVerificationPort in Verifier.__mro__


def test_plugin_executor_matches_the_existing_runner_boundary() -> None:
    signature = inspect.signature(PluginExecutor.run)

    assert tuple(signature.parameters) == (
        "self",
        "manifest",
        "payload",
        "publication_dir",
        "trusted_token",
    )
    assert signature.parameters["trusted_token"].kind is inspect.Parameter.KEYWORD_ONLY
