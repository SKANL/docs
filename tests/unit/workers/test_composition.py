from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from docs.domain.contracts import Job
from docs.workers.composition import PipelineJobConfiguration, WorkerComposition
from docs.workers.service import WorkerService


class Queue:
    def enqueue(self, job_id, payload): pass
    def claim(self, worker_id): return None
    def ack(self, job_id, worker_id): return True


class Leases:
    def acquire(self, resource, owner, ttl_seconds): return True
    def renew(self, resource, owner, ttl_seconds): return True
    def release(self, resource, owner): return True


def payload(**overrides):
    value = {"pipeline_id": "pipeline", "run_id": "run", "inputs": [], "outputs": []}
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("value", "message"),
    [(None, "job payload must be a mapping"), ({"run_id": "run"}, "pipeline_id must be a non-empty string"),
     (payload(pipeline_id=""), "pipeline_id must be a non-empty string"),
     (payload(run_id=1), "run_id must be a non-empty string"),
     (payload(inputs="file"), "inputs must be a list of non-empty strings"),
     (payload(excluded_stages=["ok", ""]), "excluded_stages must be a list of non-empty strings"),
     (payload(external_artifacts=[1]), "external_artifacts must be a list of non-empty strings")],
)
def test_payload_validation_errors_are_deterministic(value, message, tmp_path):
    with pytest.raises((TypeError, ValueError), match=rf"^{message}$"):
        PipelineJobConfiguration.from_payload(value, tmp_path)


@pytest.mark.parametrize("path", ["../outside.txt", "nested/../../outside.txt", "/absolute.txt"])
def test_paths_must_remain_relative_and_root_confined(path, tmp_path):
    with pytest.raises(ValueError):
        PipelineJobConfiguration.from_payload(payload(inputs=[path]), tmp_path)


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="inputs path escapes workspace_root"):
        PipelineJobConfiguration.from_payload(payload(inputs=["link/file.txt"]), tmp_path)


def test_handle_creates_runtime_and_forwards_all_arguments(tmp_path):
    calls = []

    class Runtime:
        def run(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "result"

    composition = WorkerComposition(lambda pipeline: (calls.append((pipeline,)), Runtime())[1], tmp_path, Queue(), Leases())
    result = composition.handle(SimpleNamespace(payload=payload(inputs=["in.txt"], outputs=["out.txt"],
        excluded_stages=["render"], external_artifacts=["artifact"])))
    assert result == "result"
    assert calls == [("pipeline",), (("run",), {"inputs": ((tmp_path / "in.txt").resolve(),), "outputs": ((tmp_path / "out.txt").resolve(),), "excluded_stages": frozenset({"render"}), "external_artifacts": ("artifact",)})]


def test_async_runtime_result_is_rejected_and_coroutine_closed(tmp_path):
    async def run(*args, **kwargs):
        return 1
    with pytest.raises(TypeError, match="pipeline runtime handler must be synchronous"):
        WorkerComposition(lambda _: type("Runtime", (), {"run": run})(), tmp_path, Queue(), Leases()).handle(SimpleNamespace(payload=payload()))


def test_create_service_wires_options_and_handler(tmp_path):
    composition = WorkerComposition(lambda _: object(), tmp_path, Queue(), Leases(), worker_id="worker", lease_ttl_seconds=9, max_retries=2)
    service = composition.create_service()
    assert isinstance(service, WorkerService)
    assert service.queue is composition._service.queue
    assert service.worker_id == "worker"
    assert service.lease_ttl_seconds == 9
    assert service.max_retries == 2
