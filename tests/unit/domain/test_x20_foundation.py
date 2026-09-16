from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from docs.domain.contracts import Artifact, Blob, Graph, Lease, Passport, Run
from docs.domain.ports.x20 import (
    ArtifactStore,
    BlobStore,
    GraphStore,
    JobQueue,
    LeaseStore,
    PassportStore,
    RunStore,
)
from docs.infrastructure.memory.x20 import (
    InMemoryArtifactStore,
    InMemoryBlobStore,
    InMemoryGraphStore,
    InMemoryJobQueue,
    InMemoryLeaseStore,
    InMemoryPassportStore,
    InMemoryRunStore,
)


class CustomMapping(Mapping[str, object]):
    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def test_mapping_inputs_are_recursively_frozen_for_contract_payloads():
    payload = MappingProxyType({"nested": CustomMapping({"items": ["original"]})})

    run = Run("run-1", payload=payload)

    assert run.payload == MappingProxyType({"nested": MappingProxyType({"items": ("original",)})})


def test_mapping_entries_are_recursively_frozen_for_passports():
    entries = (MappingProxyType({"nested": CustomMapping({"items": ["original"]})}),)

    passport = Passport("run-1", entries=entries)

    assert passport.entries == (MappingProxyType({"nested": MappingProxyType({"items": ("original",)})}),)


@pytest.mark.parametrize("contract", [Run, Passport, Artifact, Blob])
def test_from_dict_accepts_mapping_shapes(contract):
    if contract is Run:
        payload = {"id": "run-1", "payload": CustomMapping({"nested": {"value": 1}})}
    elif contract is Passport:
        payload = {"run_id": "run-1", "entries": [CustomMapping({"nested": {"value": 1}})]}
    elif contract is Artifact:
        payload = {
            "id": "artifact-1",
            "run_id": "run-1",
            "kind": "report",
            "digest": "abc",
            "metadata": MappingProxyType({"nested": {"value": 1}}),
        }
    else:
        payload = {
            "key": "blob-1",
            "digest": "abc",
            "size_bytes": 1,
            "metadata": MappingProxyType({"nested": {"value": 1}}),
        }

    value = contract.from_dict(MappingProxyType({"schema": "docs.x20/v1", **payload}))

    assert value.to_dict()["schema"] == "docs.x20/v1"


def test_contracts_are_versioned_and_json_serializable():
    values = [
        Run(id="run-1", status="queued"),
        Passport(run_id="run-1"),
        Artifact(id="artifact-1", run_id="run-1", kind="report", digest="abc"),
        Blob(key="blob-1", digest="abc", size_bytes=3),
        Graph(nodes=("run-1",), edges=()),
    ]

    for value in values:
        payload = value.to_dict()
        assert payload["schema"] == "docs.x20/v1"
        assert json.loads(json.dumps(payload)) == payload
        assert type(value).from_dict(payload) == value


def test_non_empty_passport_is_json_serializable():
    passport = Passport("run-1", entries=(MappingProxyType({"artifact": "artifact-1"}),))

    assert json.loads(json.dumps(passport.to_dict())) == passport.to_dict()


def test_in_memory_stores_are_interchangeable_ports():
    run = Run(id="run-1", status="queued")
    passport = Passport(run_id=run.id)
    artifact = Artifact(id="artifact-1", run_id=run.id, kind="report", digest="abc")
    blob = Blob(key="blob-1", digest="abc", size_bytes=3)
    graph = Graph(nodes=(run.id,), edges=())

    stores: tuple[RunStore, PassportStore, ArtifactStore, BlobStore, GraphStore] = (
        InMemoryRunStore(),
        InMemoryPassportStore(),
        InMemoryArtifactStore(),
        InMemoryBlobStore(),
        InMemoryGraphStore(),
    )
    stores[0].put(run)
    stores[1].put(passport)
    stores[2].put(artifact)
    stores[3].put(blob, b"abc")
    stores[4].put(graph)

    assert stores[0].get(run.id) == run
    assert stores[1].get(run.id) == passport
    assert stores[2].get(artifact.id) == artifact
    assert stores[3].get(blob.key) == (blob, b"abc")
    assert stores[4].get() == graph


def test_job_queue_and_lease_store_support_claim_lifecycle():
    queue: JobQueue = InMemoryJobQueue()
    leases: LeaseStore = InMemoryLeaseStore()
    queue.enqueue("job-1", {"run_id": "run-1"})

    job = queue.claim("worker-1")
    assert job is not None
    assert job.id == "job-1"
    assert leases.acquire("run-1", "worker-1", 30) is True
    assert leases.acquire("run-1", "worker-2", 30) is False
    assert leases.release("run-1", "worker-1") is True
    assert queue.ack(job.id, "worker-1") is True
    assert queue.claim("worker-2") is None


def test_job_and_lease_contracts_are_versioned():
    from docs.domain.contracts import Job, Lease

    for value in (Job("job-1", {"run_id": "run-1"}), Lease("run-1", "worker-1", 30)):
        payload = value.to_dict()
        assert payload["schema"] == "docs.x20/v1"
        assert type(value).from_dict(payload) == value


def test_lease_can_be_renewed_by_current_owner():
    leases = InMemoryLeaseStore()
    assert leases.acquire("run-1", "worker-1", 30)
    assert leases.renew("run-1", "worker-1", 60)
    assert not leases.renew("run-1", "worker-2", 90)


def test_contract_payloads_are_deeply_isolated_from_inputs_and_outputs():
    payload = {"nested": {"items": ["original"]}}
    run = Run("run-1", payload=payload)
    payload["nested"]["items"].append("mutated")

    assert run.payload["nested"]["items"] == ("original",)
    serialized = run.to_dict()
    serialized["payload"]["nested"]["items"].append("output-mutation")
    assert run.payload["nested"]["items"] == ("original",)


def test_in_memory_adapters_isolate_mutable_payloads():
    payload = {"nested": {"items": ["original"]}}
    queue = InMemoryJobQueue()
    queue.enqueue("job-1", payload)
    payload["nested"]["items"].append("input-mutation")
    job = queue.claim("worker-1")
    assert job is not None
    assert job.payload["nested"]["items"] == ("original",)
    job_payload = job.to_dict()
    job_payload["payload"]["nested"]["items"].append("output-mutation")
    assert job.payload["nested"]["items"] == ("original",)


@pytest.mark.parametrize(
    ("contract", "field", "value"),
    [
        (Run, "id", ""),
        (Run, "payload", []),
        (Passport, "entries", {}),
        (Artifact, "metadata", []),
        (Blob, "size_bytes", -1),
        (Lease, "ttl_seconds", -1),
        (Graph, "nodes", {"node": "run-1"}),
        (Graph, "edges", [["run-1"]]),
    ],
)
def test_from_dict_rejects_invalid_shapes_and_values(contract, field, value):
    payload = {"schema": "docs.x20/v1"}
    if contract is Run:
        payload.update({"id": "run-1", "payload": {}})
    elif contract is Passport:
        payload.update({"run_id": "run-1", "entries": []})
    elif contract is Artifact:
        payload.update({"id": "a-1", "run_id": "run-1", "kind": "report", "digest": "abc", "metadata": {}})
    elif contract is Blob:
        payload.update({"key": "blob-1", "digest": "abc", "size_bytes": 0, "metadata": {}})
    elif contract is Lease:
        payload.update({"resource": "run-1", "owner": "worker-1", "ttl_seconds": 0})
    else:
        payload.update({"nodes": [], "edges": []})
    payload[field] = value

    with pytest.raises((TypeError, ValueError)):
        contract.from_dict(payload)


def test_from_dict_rejects_non_exact_scalar_types_and_malformed_edges():
    with pytest.raises((TypeError, ValueError)):
        Run.from_dict({"schema": "docs.x20/v1", "id": 7})
    with pytest.raises((TypeError, ValueError)):
        Blob.from_dict({"schema": "docs.x20/v1", "key": "b", "digest": "d", "size_bytes": True})
    with pytest.raises((TypeError, ValueError)):
        Graph.from_dict({"schema": "docs.x20/v1", "nodes": ["run-1"], "edges": [["run-1", 7]]})
    with pytest.raises((TypeError, ValueError)):
        Graph.from_dict({"schema": "docs.x20/v1", "nodes": ["run-1"], "edges": [("run-1", "run-2")]})


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Run(id=""),
        lambda: Run(id="run-1", payload=[]),  # type: ignore[arg-type]  # intentionally invalid runtime input
        lambda: Blob(key="blob-1", digest="abc", size_bytes=-1),
        lambda: Lease(resource="", owner="worker-1", ttl_seconds=30),
    ],
)
def test_contract_constructors_reject_invalid_values(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_graph_constructor_copies_mutable_node_and_edge_inputs():
    nodes = ["run-1"]
    edges = [["run-1", "run-2"]]

    graph = Graph(nodes=nodes, edges=edges)
    nodes.append("run-3")
    edges[0][1] = "mutated"

    assert graph.nodes == ("run-1",)
    assert graph.edges == (("run-1", "run-2"),)


def test_expired_lease_can_be_acquired_by_another_owner():
    leases = InMemoryLeaseStore()

    assert leases.acquire("run-1", "worker-1", 0) is True
    assert leases.acquire("run-1", "worker-2", 30) is True


def test_job_queue_does_not_claim_duplicate_job_ids_concurrently():
    queue = InMemoryJobQueue()
    queue.enqueue("job-1", {"run_id": "run-1"})
    queue.enqueue("job-1", {"run_id": "run-1"})

    first_claim = queue.claim("worker-1")

    assert first_claim is not None
    assert queue.claim("worker-2") is None
    assert queue.ack("job-1", "worker-1") is True
