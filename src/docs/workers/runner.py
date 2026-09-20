"""Cooperative runtime loop for :class:`docs.workers.service.WorkerService`.

The runner deliberately owns only polling and shutdown.  Claiming, lease
management, execution, acknowledgement, and retry policy remain the service's
responsibility.
"""

from __future__ import annotations

from math import isfinite
from threading import Event

from docs.workers.service import WorkerResult, WorkerService


class WorkerRunner:
    """Poll one ``WorkerService`` until stopped or a bounded iteration limit.

    ``poll_interval`` is the wait after the first idle poll.  Each consecutive
    idle poll multiplies that delay by ``backoff``; successful work resets the
    delay.  Waiting is interruptible through :meth:`stop`, and no signal,
    process, or background-thread side effects are installed by this module.
    """

    def __init__(
        self,
        service: WorkerService,
        *,
        poll_interval: float = 1.0,
        backoff: float = 1.0,
    ) -> None:
        """Create a runner for an already-configured worker service.

        Args:
            service: The service responsible for processing a claimed job.
            poll_interval: Base seconds to wait after an idle poll.
            backoff: Non-decreasing multiplier for consecutive idle waits.

        Raises:
            ValueError: If timing values are not finite non-negative values,
                or if ``backoff`` is less than one.
        """
        if not isfinite(poll_interval) or poll_interval < 0:
            raise ValueError("poll_interval must be a finite non-negative value")
        if not isfinite(backoff) or backoff < 1:
            raise ValueError("backoff must be a finite value of at least one")

        self._service = service
        self.poll_interval = float(poll_interval)
        self.backoff = float(backoff)
        self._stopped = Event()

    @property
    def worker_id(self) -> str:
        """Return the identity used by the injected service to claim jobs."""
        return self._service.worker_id

    @property
    def stopped(self) -> bool:
        """Report whether cooperative shutdown has been requested."""
        return self._stopped.is_set()

    def run_once(self) -> WorkerResult | None:
        """Attempt exactly one synchronous service run unless already stopped."""
        if self.stopped:
            return None
        return self._service.run_sync()

    def run_until_stopped(self, max_iterations: int | None = None) -> list[WorkerResult]:
        """Run synchronously until stopped or ``max_iterations`` is reached.

        An iteration is one :meth:`run_once` call, including an idle poll.
        Results are returned in execution order.  Service exceptions propagate
        unchanged so that callers can choose their own failure policy.
        """
        if max_iterations is not None and max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")

        results: list[WorkerResult] = []
        iterations = 0
        idle_polls = 0
        while not self.stopped and (max_iterations is None or iterations < max_iterations):
            result = self.run_once()
            iterations += 1
            if result is not None:
                results.append(result)
                idle_polls = 0
                continue

            idle_polls += 1
            if self.stopped or (max_iterations is not None and iterations >= max_iterations):
                continue
            self._stopped.wait(self.poll_interval * self.backoff ** (idle_polls - 1))

        return results

    def stop(self) -> None:
        """Request shutdown and interrupt any current idle wait."""
        self._stopped.set()

    def __enter__(self) -> WorkerRunner:
        """Return this runner for use in a ``with`` statement."""
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        """Request shutdown without suppressing an exception from the body."""
        self.stop()
        return False
