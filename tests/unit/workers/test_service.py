from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from docs.domain.contracts import Job, Run
from docs.workers.service import WorkerResult, WorkerService


class FakeQueue:
    def __init__(self, *jobs: Job) -> None:
        self.jobs = list(jobs)
        self.enqueued: list[tuple[str, dict[str, object]]] = []
        self.acked: list[tuple[str, str]] = []
        self.ack_result = True

    def enqueue(self, job_id: str, payload: dict[str, object]) -> None:
        self.enqueued.append((job_id, payload))

    def claim(self, worker_id: str) -> Job | None:
        return self.jobs.pop(0) if self.jobs else None

    def ack(self, job_id: str, worker_id: str) -> bool:
        self.acked.append((job_id, worker_id))
        return self.ack_result


class FakeLeases:
    def __init__(self, *, acquire: bool = True, renew: bool = True) -> None:
        self.acquire_result = acquire
        self.renew_result = renew
        self.acquired: list[tuple[str, str, int]] = []
        self.renewed: list[tuple[str, str, int]] = []
        self.released: list[tuple[str, str]] = []

    def acquire(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        self.acquired.append((resource, owner, ttl_seconds))
        return self.acquire_result

    def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
        self.renewed.append((resource, owner, ttl_seconds))
        return self.renew_result

    def release(self, resource: str, owner: str) -> bool:
        self.released.append((resource, owner))
        return True


def make_service(tmp_path: Path, job: Job, handler, **kwargs) -> tuple[WorkerService, FakeQueue, FakeLeases]:
    queue = FakeQueue(job)
    leases = FakeLeases()
    return WorkerService(queue, leases, handler, scratch_parent=tmp_path, worker_id="worker-1", **kwargs), queue, leases


def test_success_passes_job_and_scratch_to_handler_and_cleans_scratch(tmp_path: Path) -> None:
    seen_job: Job | None = None
    seen_scratch: Path | None = None

    def handler(job: Job, scratch: Path) -> str:
        nonlocal seen_job, seen_scratch
        seen_job = job
        seen_scratch = scratch
        (scratch / "artifact").write_text("data")
        return "ok"

    service, queue, leases = make_service(tmp_path, Job("job-1", {"run_id": "run-1"}), handler)
    result = service.run_sync()

    assert result is not None and (result.state, result.value) == ("succeeded", "ok")
    assert seen_job is not None and seen_job.id == "job-1"
    assert seen_scratch is not None and not seen_scratch.exists()
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]


def test_failure_enqueues_retry_with_retry_of_and_cleans_up(tmp_path: Path) -> None:
    service, queue, leases = make_service(
        tmp_path,
        Job("job-1", {"run_id": "run-1", "attempt": 1}),
        lambda job: (_ for _ in ()).throw(RuntimeError("boom")),
        max_retries=1,
    )
    result = service.run_sync()

    assert result is not None and result.state == "failed" and result.error == "boom"
    assert queue.enqueued == [("job-1:retry:1", {"run_id": "run-1", "attempt": 2, "retry_of": "job-1"})]
    assert not list(tmp_path.iterdir())
    assert leases.released == [("run-1", "worker-1")]


def test_sync_rejects_custom_awaitable_handler_result(tmp_path: Path) -> None:
    class CustomAwaitable:
        def __await__(self):
            async def resolve() -> int:
                return 42

            return resolve().__await__()

    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: CustomAwaitable())

    result = service.run_sync()

    assert result is not None
    assert result.state == "failed"
    assert result.error == "run_sync cannot execute an awaitable handler"
    assert queue.acked == [("job-1", "worker-1")]


def test_cancellation_before_handler_is_finalized(tmp_path: Path) -> None:
    called = False

    def handler(job: Job) -> None:
        nonlocal called
        called = True

    service, queue, leases = make_service(tmp_path, Job("job-1", {"run_id": "run-1"}), handler)
    service.cancel("run-1")

    result = service.run_sync()
    assert result is not None and result.state == "cancelled"
    assert not called and queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]


def test_busy_lease_does_not_call_handler_or_release_unowned_lease(tmp_path: Path) -> None:
    leases = FakeLeases(acquire=False)
    queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
    service = WorkerService(
        queue, leases, lambda job: pytest.fail("handler called"), scratch_parent=tmp_path, worker_id="worker-1"
    )

    result = service.run_sync()
    assert result is not None and result.state == "busy"
    assert leases.released == [] and queue.acked == [("job-1", "worker-1")]


def test_heartbeat_renews_owned_lease(tmp_path: Path) -> None:
    service, _, leases = make_service(tmp_path, Job("job-1"), lambda job: None, lease_ttl_seconds=17)
    assert service.heartbeat("run-1") is True
    assert leases.renewed == [("run-1", "worker-1", 17)]


def test_lease_renewal_loss_stops_work_without_success_finalization(tmp_path: Path) -> None:
    called = False
    finalized: list[WorkerResult] = []

    def handler(job: Job) -> str:
        nonlocal called
        called = True
        return "must not run"

    service, queue, leases = make_service(
        tmp_path, Job("job-1", {"run_id": "run-1"}), handler, finalizer=finalized.append
    )
    leases.renew_result = False

    result = service.run_sync()

    assert result is not None and result.state == "lease_lost"
    assert not called and finalized == [] and queue.acked == []


def test_heartbeat_renews_periodically_while_sync_handler_runs(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()

    def handler(job: Job) -> str:
        started.set()
        assert finish.wait(2)
        return "ok"

    service, _, leases = make_service(
        tmp_path,
        Job("job-1", {"run_id": "run-1"}),
        handler,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    result_holder: list[WorkerResult] = []
    thread = threading.Thread(target=lambda: result_holder.append(service.run_sync()))
    thread.start()
    assert started.wait(2)
    deadline = threading.Event()
    while len(leases.renewed) < 3 and not deadline.wait(0.01):
        pass
    finish.set()
    thread.join(2)

    assert result_holder and result_holder[0] is not None
    assert result_holder[0].state == "succeeded"
    assert len(leases.renewed) >= 3


def test_periodic_heartbeat_loss_fails_closed_after_sync_handler_returns(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()
    finalized: list[WorkerResult] = []

    class LosingLeases(FakeLeases):
        def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
            self.renewed.append((resource, owner, ttl_seconds))
            return len(self.renewed) < 2

    def handler(job: Job) -> str:
        started.set()
        assert finish.wait(2)
        return "must not be published"

    queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
    leases = LosingLeases()
    service = WorkerService(
        queue,
        leases,
        handler,
        finalizer=finalized.append,
        scratch_parent=tmp_path,
        worker_id="worker-1",
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.01,
    )
    result_holder: list[WorkerResult] = []
    thread = threading.Thread(target=lambda: result_holder.append(service.run_sync()))
    thread.start()
    assert started.wait(2)
    while len(leases.renewed) < 2:
        threading.Event().wait(0.01)
    finish.set()
    thread.join(2)

    assert result_holder and result_holder[0] is not None
    assert result_holder[0].state == "lease_lost"
    assert finalized == [] and queue.acked == []


def test_durable_cancellation_is_observed_from_run_store(tmp_path: Path) -> None:
    class Runs:
        def __init__(self) -> None:
            self.items: dict[str, object] = {}

        def put(self, run: object) -> None:
            self.items[run.id] = run  # type: ignore[attr-defined]

        def get(self, run_id: str) -> object | None:
            return self.items.get(run_id)

    runs = Runs()
    service, queue, _ = make_service(
        tmp_path,
        Job("job-1", {"run_id": "run-1"}),
        lambda job: (runs.put(Run("run-1", "cancelled")) or "ignored"),
    )
    service.run_store = runs  # type: ignore[assignment]

    result = service.run_sync()

    assert result is not None and result.state == "cancelled"
    assert queue.acked == [("job-1", "worker-1")]


def test_async_heartbeat_renews_periodically_while_coroutine_runs(tmp_path: Path) -> None:
    async def handler(job: Job) -> str:
        await asyncio.sleep(0.05)
        return "ok"

    service, _, leases = make_service(
        tmp_path,
        Job("job-1", {"run_id": "run-1"}),
        handler,
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.01,
    )

    result = asyncio.run(service.run_async())

    assert result is not None and result.state == "succeeded"
    assert len(leases.renewed) >= 3


def test_async_heartbeat_loss_cancels_coroutine_and_does_not_ack(tmp_path: Path) -> None:
    started = asyncio.Event()

    class LosingLeases(FakeLeases):
        def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
            self.renewed.append((resource, owner, ttl_seconds))
            return len(self.renewed) < 2

    async def handler(job: Job) -> str:
        started.set()
        await asyncio.sleep(60)
        return "must not publish"

    queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
    leases = LosingLeases()
    service = WorkerService(
        queue,
        leases,
        handler,
        scratch_parent=tmp_path,
        worker_id="worker-1",
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=0.01,
    )

    async def exercise() -> WorkerResult | None:
        task = asyncio.create_task(service.run_async())
        await started.wait()
        return await task

    result = asyncio.run(exercise())

    assert result is not None and result.state == "lease_lost"
    assert queue.acked == [] and leases.released == []


def test_job_id_is_sanitized_and_scratch_stays_contained(tmp_path: Path) -> None:
    seen_scratch: Path | None = None

    def handler(job: Job, scratch: Path) -> None:
        nonlocal seen_scratch
        seen_scratch = scratch

    service, _, _ = make_service(tmp_path, Job("../escape", {"run_id": "run-1"}), handler)
    result = service.run_sync()

    assert result is not None and result.state == "succeeded"
    assert seen_scratch is not None
    scratch = seen_scratch
    assert scratch.parent == tmp_path.resolve()
    assert ".." not in scratch.name and "/" not in scratch.name and "\\" not in scratch.name
    assert not (tmp_path.parent / "escape").exists()


def test_failed_finalization_is_retryable_and_not_cached(tmp_path: Path) -> None:
    attempts = 0

    def finalizer(result: WorkerResult) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("finalizer unavailable")

    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: "ok", finalizer=finalizer)
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1", value="ok")

    with pytest.raises(RuntimeError, match="finalizer unavailable"):
        service._finalize(result)
    assert service._finalize(result) == result
    assert attempts == 2 and queue.acked == [("job-1", "worker-1")]


def test_ack_failure_does_not_cache_finalization(tmp_path: Path) -> None:
    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: "ok")
    queue.ack_result = False
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1", value="ok")

    with pytest.raises(RuntimeError, match="ack"):
        service._finalize(result)
    queue.ack_result = True
    assert service._finalize(result) == result
    assert queue.acked == [("job-1", "worker-1"), ("job-1", "worker-1")]


def test_finalizer_success_is_deduplicated_when_ack_fails(tmp_path: Path) -> None:
    finalizer_calls: list[WorkerResult] = []
    service, queue, _ = make_service(
        tmp_path, Job("job-1"), lambda job: "ok", finalizer=finalizer_calls.append
    )
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1", value="ok")
    queue.ack_result = False

    with pytest.raises(RuntimeError, match="ack"):
        service._finalize(result)

    queue.ack_result = True
    assert service._finalize(result) == result
    assert finalizer_calls == [result]
    assert queue.acked == [("job-1", "worker-1"), ("job-1", "worker-1")]


def test_finalizer_completion_is_durable_across_service_restarts(tmp_path: Path) -> None:
    class Runs:
        def __init__(self) -> None:
            self.items: dict[str, Run] = {}

        def put(self, run: Run) -> None:
            self.items[run.id] = run

        def get(self, run_id: str) -> Run | None:
            return self.items.get(run_id)

    runs = Runs()
    first_calls: list[WorkerResult] = []
    first_service, first_queue, _ = make_service(
        tmp_path, Job("job-1"), lambda job: "ok", finalizer=first_calls.append
    )
    first_service.run_store = runs  # type: ignore[assignment]
    first_queue.ack_result = False
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1", value="ok")

    with pytest.raises(RuntimeError, match="ack"):
        first_service._finalize(result)

    second_calls: list[WorkerResult] = []
    second_service, second_queue, _ = make_service(
        tmp_path, Job("job-1"), lambda job: "ok", finalizer=second_calls.append
    )
    second_service.run_store = runs  # type: ignore[assignment]

    assert second_service._finalize(result) == result
    assert first_calls == [result] and second_calls == []
    assert second_queue.acked == [("job-1", "worker-1")]


def test_concurrent_finalization_runs_side_effects_once(tmp_path: Path) -> None:
    finalized: list[WorkerResult] = []
    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: "ok", finalizer=finalized.append)
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1", value="ok")
    errors: list[Exception] = []

    def finalize() -> None:
        try:
            service._finalize(result)
        except Exception as exc:  # pragma: no cover - diagnostic assertion below
            errors.append(exc)

    threads = [threading.Thread(target=finalize) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [] and finalized == [result] and queue.acked == [("job-1", "worker-1")]


def test_duplicate_finalization_returns_original_and_calls_finalizer_once(tmp_path: Path) -> None:
    finalized: list[WorkerResult] = []
    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: "ok", finalizer=finalized.append)
    first = service.run_sync()
    duplicate = service._finalize(first)  # type: ignore[arg-type]
    assert duplicate == first and finalized == [first] and queue.acked == [("job-1", "worker-1")]


def test_async_entrypoint_runs_once() -> None:
    queue = FakeQueue(Job("job-1"))
    service = WorkerService(queue, FakeLeases(), lambda job: 42, worker_id="worker-1")
    result = asyncio.run(service.run_async())
    assert result is not None and result.value == 42


def test_async_entrypoint_awaits_awaitable_handler_result() -> None:
    queue = FakeQueue(Job("job-1"))

    async def handler(job: Job) -> int:
        await asyncio.sleep(0)
        return 42

    service = WorkerService(queue, FakeLeases(), handler, worker_id="worker-1")
    result = asyncio.run(service.run_async())

    assert result is not None and result.value == 42


@pytest.mark.parametrize("kwargs", [{"lease_ttl_seconds": 0}, {"lease_ttl_seconds": -1}, {"max_retries": -1}])
def test_invalid_config_is_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="lease_ttl_seconds"):
        WorkerService(FakeQueue(), FakeLeases(), lambda job: None, **kwargs)  # type: ignore[arg-type]


def test_lease_loss_cleanup_does_not_release_reacquired_lease(tmp_path: Path) -> None:
    class ReacquiringLeases(FakeLeases):
        def renew(self, resource: str, owner: str, ttl_seconds: int) -> bool:
            self.released.append((resource, "new-owner"))
            return False

        def release(self, resource: str, owner: str) -> bool:
            self.released.append((resource, owner))
            return True

    leases = ReacquiringLeases()
    service, _, _ = make_service(tmp_path, Job("job-1", {"run_id": "run-1"}), lambda job: None)
    service.leases = leases
    result = service.run_sync()
    assert result is not None and result.state == "lease_lost"
    assert leases.released == [("run-1", "new-owner")]


def test_async_offloads_blocking_lifecycle_and_awaits_async_finalizer(tmp_path: Path) -> None:
    event_loop_thread = threading.get_ident()
    threads: list[int] = []
    finalized: list[WorkerResult] = []

    def handler(job: Job) -> int:
        threads.append(threading.get_ident())
        return 42

    async def finalizer(result: WorkerResult) -> None:
        await asyncio.sleep(0)
        finalized.append(result)

    service, _, _ = make_service(tmp_path, Job("job-1"), handler, finalizer=finalizer)
    result = asyncio.run(service.run_async())
    assert result is not None and result.value == 42
    assert finalized == [result]
    assert threads and threads[0] != event_loop_thread


def test_async_cancellation_finalizes_acknowledges_and_cleans_before_reraising(tmp_path: Path) -> None:
    started = asyncio.Event()
    finalized: list[WorkerResult] = []

    async def handler(job: Job, scratch: Path) -> int:
        (scratch / "partial").write_text("data")
        started.set()
        await asyncio.sleep(60)
        return 42

    async def finalizer(result: WorkerResult) -> None:
        finalized.append(result)

    async def exercise() -> tuple[FakeQueue, FakeLeases, list[WorkerResult]]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = FakeLeases()
        service = WorkerService(
            queue, leases, handler, finalizer=finalizer, scratch_parent=tmp_path, worker_id="worker-1"
        )
        task = asyncio.create_task(service.run_async())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return queue, leases, finalized

    queue, leases, results = asyncio.run(exercise())
    assert results and results[0].state == "cancelled"
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]
    assert not list(tmp_path.iterdir())


def test_async_cancellation_waits_for_sync_handler_before_cleanup_and_release(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()
    scratch_seen: Path | None = None

    def handler(job: Job, scratch: Path) -> int:
        nonlocal scratch_seen
        scratch_seen = scratch
        (scratch / "partial").write_text("data")
        started.set()
        assert finish.wait(5)
        return 42

    async def exercise() -> tuple[FakeQueue, FakeLeases, Path]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = FakeLeases()
        service = WorkerService(queue, leases, handler, scratch_parent=tmp_path, worker_id="worker-1")
        task = asyncio.create_task(service.run_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert scratch_seen is not None and scratch_seen.exists()
        assert leases.released == []
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return queue, leases, scratch_seen

    queue, leases, scratch = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]
    assert not scratch.exists()


def test_async_cancellation_during_claim_acknowledges_claimed_job() -> None:
    started = threading.Event()
    finish = threading.Event()

    class BlockingClaimQueue(FakeQueue):
        def claim(self, worker_id: str) -> Job | None:
            job = super().claim(worker_id)
            started.set()
            assert finish.wait(5)
            return job

    async def exercise() -> tuple[BlockingClaimQueue, asyncio.CancelledError]:
        queue = BlockingClaimQueue(Job("job-1"))
        service = WorkerService(queue, FakeLeases(), lambda job: pytest.fail("handler called"), worker_id="worker-1")
        task = asyncio.create_task(service.run_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        return queue, cancelled.value

    queue, _ = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]


def test_async_cancellation_during_lease_acquisition_releases_and_acknowledges(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()

    class BlockingAcquireLeases(FakeLeases):
        def acquire(self, resource: str, owner: str, ttl_seconds: int) -> bool:
            self.acquired.append((resource, owner, ttl_seconds))
            started.set()
            assert finish.wait(5)
            return True

    async def exercise() -> tuple[FakeQueue, BlockingAcquireLeases]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = BlockingAcquireLeases()
        service = WorkerService(queue, leases, lambda job: pytest.fail("handler called"), worker_id="worker-1")
        task = asyncio.create_task(service.run_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return queue, leases

    queue, leases = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]


def test_async_cancellation_during_scratch_path_acquisition_releases_and_acknowledges(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()

    def scratch_path(job_id: str) -> Path:
        started.set()
        assert finish.wait(5)
        return tmp_path / ".worker-job-1"

    async def exercise() -> tuple[FakeQueue, FakeLeases]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = FakeLeases()
        service = WorkerService(queue, leases, lambda job: pytest.fail("handler called"), worker_id="worker-1")
        service._scratch_path = scratch_path  # type: ignore[method-assign]
        task = asyncio.create_task(service.run_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and leases.released == []
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return queue, leases

    queue, leases = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]


def test_async_cancellation_during_run_store_write_drains_before_cleanup(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()

    class BlockingRunStore:
        def put(self, run: object) -> None:
            started.set()
            assert finish.wait(5)

    async def exercise() -> tuple[FakeQueue, FakeLeases]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = FakeLeases()
        service = WorkerService(
            queue,
            leases,
            lambda job: pytest.fail("handler called"),
            run_store=BlockingRunStore(),  # type: ignore[arg-type]
            scratch_parent=tmp_path,
            worker_id="worker-1",
        )
        task = asyncio.create_task(service.run_async())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and leases.released == []
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return queue, leases

    queue, leases = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]
    assert leases.released == [("run-1", "worker-1")]
    assert not list(tmp_path.iterdir())


def test_shield_and_drain_surfaces_drained_operation_failure_after_cancellation() -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def operation() -> None:
        started.set()
        await finish.wait()
        raise AssertionError("background lifecycle assertion failed")

    async def exercise() -> None:
        service = WorkerService(FakeQueue(), FakeLeases(), lambda job: None, worker_id="worker-1")
        task = asyncio.create_task(service._shield_and_drain(operation()))
        await started.wait()
        task.cancel()
        finish.set()
        with pytest.raises(AssertionError, match="background lifecycle assertion failed"):
            await task

    asyncio.run(exercise())


def test_async_cleanup_failure_is_not_acknowledged_after_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()

    async def handler(job: Job, scratch: Path) -> int:
        started.set()
        await asyncio.sleep(60)
        return 42

    def broken_rmtree(path: Path, *, ignore_errors: bool) -> None:
        raise AssertionError("cleanup failed")

    monkeypatch.setattr("docs.workers.service.shutil.rmtree", broken_rmtree)

    async def exercise() -> tuple[FakeQueue, FakeLeases]:
        queue = FakeQueue(Job("job-1", {"run_id": "run-1"}))
        leases = FakeLeases()
        service = WorkerService(
            queue, leases, handler, scratch_parent=Path.cwd(), worker_id="worker-1"
        )
        task = asyncio.create_task(service.run_async())
        await started.wait()
        task.cancel()
        with pytest.raises(AssertionError, match="cleanup failed"):
            await task
        return queue, leases

    queue, leases = asyncio.run(exercise())
    assert queue.acked == []
    assert leases.released == []


def test_concurrent_async_finalization_serializes_side_effects_once(tmp_path: Path) -> None:
    finalized: list[WorkerResult] = []

    async def finalizer(result: WorkerResult) -> None:
        await asyncio.sleep(0)
        finalized.append(result)

    async def exercise() -> tuple[WorkerService, FakeQueue, WorkerResult]:
        queue = FakeQueue(Job("job-1"))
        service = WorkerService(queue, FakeLeases(), lambda job: None, finalizer=finalizer, worker_id="worker-1")
        result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1")
        results = await asyncio.wait_for(
            asyncio.gather(service._finalize_async(result), service._finalize_async(result)), timeout=1
        )
        assert results == [result, result]
        return service, queue, result

    service, queue, result = asyncio.run(exercise())
    assert finalized == [result]
    assert queue.acked == [("job-1", "worker-1")]
    assert service._finalized["job-1"] == result


def test_async_finalization_across_event_loops_shares_side_effect_coordination(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()
    finalized: list[WorkerResult] = []

    async def finalizer(result: WorkerResult) -> None:
        started.set()
        await asyncio.to_thread(finish.wait, 5)
        finalized.append(result)

    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: None, finalizer=finalizer)
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1")
    results: list[WorkerResult] = []

    def finalize() -> None:
        results.append(asyncio.run(service._finalize_async(result)))

    threads = [threading.Thread(target=finalize) for _ in range(2)]
    threads[0].start()
    assert started.wait(5)
    threads[1].start()
    finish.set()
    for thread in threads:
        thread.join(5)

    assert not any(thread.is_alive() for thread in threads)
    assert results == [result, result]
    assert finalized == [result]
    assert queue.acked == [("job-1", "worker-1")]


def test_sync_and_async_finalization_share_side_effect_coordination(tmp_path: Path) -> None:
    started = threading.Event()
    finish = threading.Event()
    finalized: list[WorkerResult] = []

    async def finalizer(result: WorkerResult) -> None:
        started.set()
        await asyncio.to_thread(finish.wait, 5)
        finalized.append(result)

    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: None, finalizer=finalizer)
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1")
    async_results: list[WorkerResult] = []

    def finalize_async() -> None:
        async_results.append(asyncio.run(service._finalize_async(result)))

    async_thread = threading.Thread(target=finalize_async)
    async_thread.start()
    assert started.wait(5)
    sync_results: list[WorkerResult] = []
    sync_thread = threading.Thread(target=lambda: sync_results.append(service._finalize(result)))
    sync_thread.start()
    finish.set()
    async_thread.join(5)
    sync_thread.join(5)

    assert not async_thread.is_alive() and not sync_thread.is_alive()
    assert async_results == [result] and sync_results == [result]
    assert finalized == [result]
    assert queue.acked == [("job-1", "worker-1")]


def test_sync_finalization_rejects_awaitable_finalizer_without_ack_or_completion(tmp_path: Path) -> None:
    finalized: list[WorkerResult] = []

    async def finalizer(result: WorkerResult) -> None:
        finalized.append(result)

    service, queue, _ = make_service(tmp_path, Job("job-1"), lambda job: None, finalizer=finalizer)
    result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1")

    with pytest.raises(TypeError, match="run_sync cannot execute an awaitable finalizer"):
        service._finalize(result)

    assert finalized == []
    assert queue.acked == []
    assert service._finalizer_completed == set()
    assert service._finalized == {}


def test_async_finalization_completes_ack_and_cache_before_reraising_cancellation(tmp_path: Path) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    finalized: list[WorkerResult] = []

    async def finalizer(result: WorkerResult) -> None:
        started.set()
        await finish.wait()
        finalized.append(result)

    async def exercise() -> tuple[WorkerService, FakeQueue, WorkerResult]:
        queue = FakeQueue(Job("job-1"))
        service = WorkerService(queue, FakeLeases(), lambda job: None, finalizer=finalizer, worker_id="worker-1")
        result = WorkerResult("job-1", "job-1", "succeeded", worker_id="worker-1")
        task = asyncio.create_task(service._finalize_async(result))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert queue.acked == []
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return service, queue, result

    service, queue, result = asyncio.run(exercise())
    assert queue.acked == [("job-1", "worker-1")]
    assert service._finalized["job-1"] == result
    assert finalized == [result]
