from __future__ import annotations

import inspect
from typing import Protocol

from docs.domain.ports.blob_store import BlobStore
from docs.domain.ports.job_queue import CancellableJobQueue, JobQueue
from docs.domain.ports.lease_store import LeaseStore
from docs.domain.ports.run_store import ArtifactStore, PassportStore, RunStore
from docs.domain.runtime_records import SCHEMA
from docs.plugins.runner import PluginRunner


def test_public_port_contract_is_explicitly_versioned() -> None:
    assert SCHEMA == "docs.runtime/v1"


def test_runtime_ports_are_protocols() -> None:
    for port in (
        ArtifactStore,
        BlobStore,
        CancellableJobQueue,
        JobQueue,
        LeaseStore,
        PassportStore,
        RunStore,
    ):
        assert issubclass(port, Protocol)  # type: ignore[arg-type]


def test_plugin_runner_keeps_the_versioned_run_boundary() -> None:
    signature = inspect.signature(PluginRunner.run)

    assert tuple(signature.parameters) == (
        "self",
        "manifest",
        "payload",
        "publication_dir",
        "trusted_token",
        "artifact_digest",
    )
    assert signature.parameters["trusted_token"].kind is inspect.Parameter.KEYWORD_ONLY
