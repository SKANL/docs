from __future__ import annotations

import threading

import pytest

from docs.workers.runner import WorkerRunner
from docs.workers.service import WorkerResult


class FakeService:
    worker_id = "worker-1"

    def __init__(self, *results: WorkerResult | None) -> None:
        self.results = list(results)
        self.calls = 0
        self.called = threading.Event()

    def run_sync(self) -> WorkerResult | None:
        self.calls += 1
        self.called.set()
        return self.results.pop(0) if self.results else None


def result(job_id: str) -> WorkerResult:
    return WorkerResult(job_id, job_id, "succeeded", worker_id="worker-1")


def test_run_once_does_nothing_when_stopped() -> None:
    service = FakeService(result("job-1"))
    runner = WorkerRunner(service)
    runner.stop()

    assert runner.run_once() is None
    assert service.calls == 0


def test_run_until_stopped_respects_bounded_iterations() -> None:
    service = FakeService(result("job-1"), result("job-2"))
    runner = WorkerRunner(service, poll_interval=0)

    assert runner.run_until_stopped(max_iterations=2) == [result("job-1"), result("job-2")]
    assert service.calls == 2


def test_idle_backoff_resets_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService(None, None, result("job-1"), None, None)
    runner = WorkerRunner(service, poll_interval=2, backoff=3)
    waits: list[float] = []
    monkeypatch.setattr(runner._stopped, "wait", lambda timeout: waits.append(timeout) or False)

    runner.run_until_stopped(max_iterations=5)

    assert waits == [2.0, 6.0, 2.0]


def test_stop_interrupts_idle_wait() -> None:
    service = FakeService(None)
    runner = WorkerRunner(service, poll_interval=60)
    finished = threading.Event()

    thread = threading.Thread(target=lambda: (runner.run_until_stopped(), finished.set()))
    thread.start()
    assert service.called.wait(1)
    runner.stop()
    assert finished.wait(1)
    thread.join()


@pytest.mark.parametrize(
    ("poll_interval", "backoff"),
    [(float("nan"), 1), (float("inf"), 1), (-1, 1), (1, float("nan")), (1, float("inf")), (1, 0.5)],
)
def test_invalid_options_are_rejected(poll_interval: float, backoff: float) -> None:
    with pytest.raises(ValueError):
        WorkerRunner(FakeService(), poll_interval=poll_interval, backoff=backoff)


def test_negative_max_iterations_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        WorkerRunner(FakeService()).run_until_stopped(max_iterations=-1)


def test_context_manager_stops_runner_and_preserves_exception() -> None:
    runner = WorkerRunner(FakeService())
    with pytest.raises(RuntimeError, match="boom"), runner:
        raise RuntimeError("boom")
    assert runner.stopped


def test_service_exception_propagates_unchanged() -> None:
    error = RuntimeError("service failed")

    class FailingService(FakeService):
        def run_sync(self) -> WorkerResult | None:
            raise error

    with pytest.raises(RuntimeError) as raised:
        WorkerRunner(FailingService()).run_until_stopped(max_iterations=1)
    assert raised.value is error
