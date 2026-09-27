from __future__ import annotations

import inspect
from typing import Protocol

from docs.domain.ports.blob_store import BlobStore
from docs.domain.ports.graph_store import GraphStore
from docs.domain.ports.job_queue import CancellableJobQueue, JobQueue
from docs.domain.ports.lease_store import LeaseStore
from docs.domain.ports.plugin_executor import PluginExecutor
from docs.domain.ports.run_store import ArtifactStore, PassportStore, RunStore
from docs.domain.runtime_records import SCHEMA


def test_public_port_contract_is_explicitly_versioned() -> None:
    assert SCHEMA == "docs.x20/v1"


def test_runtime_ports_are_protocols() -> None:
    for port in (
        ArtifactStore,
        BlobStore,
        CancellableJobQueue,
        GraphStore,
        JobQueue,
        LeaseStore,
        PassportStore,
        PluginExecutor,
        RunStore,
    ):
        assert issubclass(port, Protocol)  # type: ignore[arg-type]


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
