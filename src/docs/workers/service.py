"""Port-driven worker orchestration for X20 jobs.

The service deliberately knows nothing about persistence or rendering details;
those concerns are supplied as ports (small objects with the methods used
below).  Job payloads are treated as immutable input and all work is confined
to a per-attempt scratch directory.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import re
import shutil
import tempfile
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docs.domain.contracts import Job, Run
from docs.domain.ports.x20 import JobQueue, LeaseStore, PassportStore, RunStore
from docs.observability import NoOpObservability, ObservabilityPort


class _LeaseLost(RuntimeError):
    """Internal signal used to prevent publishing work after lease loss."""


class _SyncHeartbeat:
    def __init__(self, service: WorkerService, run_id: str, interval_seconds: float) -> None:
        self._service = service
        self._run_id = run_id
        self._interval_seconds = interval_seconds
        self.lost = threading.Event()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{run_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stopped.wait(self._interval_seconds):
            try:
                renewed = self._service.heartbeat(self._run_id)
            except Exception:
                renewed = False
            if not renewed:
                self.lost.set()
                return


@dataclass(frozen=True)
class WorkerResult:
    job_id: str
    run_id: str
    state: str
    attempt: int = 1
    retry_of: str | None = None
    worker_id: str = ""
    value: Any = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class WorkerService:
    """Execute one claimed job with lease ownership and idempotent finalization."""

    def __init__(
        self,
        queue: JobQueue,
        leases: LeaseStore,
        handler: Callable[..., Any],
        *,
        run_store: RunStore | None = None,
        passport_store: PassportStore | None = None,
        finalizer: Callable[[WorkerResult], Any] | None = None,
        scratch_parent: str | Path | None = None,
        worker_id: str | None = None,
        lease_ttl_seconds: int = 60,
        heartbeat_interval_seconds: float | None = None,
        max_retries: int = 0,
        observability: ObservabilityPort | None = None,
    ) -> None:
        if lease_ttl_seconds <= 0 or max_retries < 0:
            raise ValueError("lease_ttl_seconds must be positive and max_retries non-negative")
        heartbeat_interval = lease_ttl_seconds / 3 if heartbeat_interval_seconds is None else heartbeat_interval_seconds
        if not math.isfinite(heartbeat_interval) or heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval_seconds must be a finite positive value")
        self.queue, self.leases, self.handler = queue, leases, handler
        self.run_store, self.passport_store = run_store, passport_store
        self.finalizer = finalizer
        self.scratch_parent = Path(scratch_parent or tempfile.gettempdir()).resolve()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex}"
        self.lease_ttl_seconds, self.max_retries = lease_ttl_seconds, max_retries
        self.heartbeat_interval_seconds = float(heartbeat_interval)
        self.observability = observability or NoOpObservability()
        self._finalized: dict[str, WorkerResult] = {}
        self._cancelled: set[str] = set()
        self._state_lock = threading.RLock()
        self._finalization_condition = threading.Condition(self._state_lock)
        self._finalizing: set[str] = set()
        self._finalizer_completed: set[str] = set()

    def cancel(self, run_id: str) -> None:
        with self._state_lock:
            if run_id in self._cancelled:
                return
            self._cancelled.add(run_id)
        cancel = getattr(self.queue, "cancel", None)
        if callable(cancel):
            cancel(run_id)
        if self.run_store is not None:
            try:
                run = self.run_store.get(run_id)
            except (AttributeError, OSError):
                run = None
            if run is not None and run.status not in {"cancelled", "completed", "failed", "succeeded"}:
                self.run_store.put(Run(run.id, status="cancelled", payload=run.payload, created_at=run.created_at))

    def heartbeat(self, run_id: str) -> bool:
        return self.leases.renew(run_id, self.worker_id, self.lease_ttl_seconds)

    def run_sync(self) -> WorkerResult | None:
        with self.observability.span("docs.worker.run", {"worker_id": self.worker_id}):
            job = self.queue.claim(self.worker_id)
            if job is None:
                return None
            result = self._execute(job)
            self.observability.increment(
                "docs.worker.completed",
                attributes={"state": result.state},
            )
            return result

    async def run_async(self) -> WorkerResult | None:
        job, cancellation = await self._shield_and_drain(
            asyncio.to_thread(self.queue.claim, self.worker_id)
        )
        if cancellation is not None:
            if job is not None:
                payload = dict(job.payload)
                result = WorkerResult(
                    job.id,
                    str(payload.get("run_id", job.id)),
                    "cancelled",
                    int(payload.get("attempt", 1)),
                    payload.get("retry_of"),
                    self.worker_id,
                )
                await self._finalize_async(result)
            raise cancellation
        if job is None:
            return None
        return await self._execute_async(job)

    # Convenient entry-point aliases used by adapters.
    run = run_sync
    run_once = run_sync

    def _execute(self, job: Job) -> WorkerResult:
        payload = dict(job.payload)
        run_id = str(payload.get("run_id", job.id))
        retry_of = payload.get("retry_of")
        attempt = int(payload.get("attempt", 1))
        with self._state_lock:
            prior = self._finalized.get(job.id)
        if prior is not None:
            return prior
        owned = self.leases.acquire(run_id, self.worker_id, self.lease_ttl_seconds)
        if not owned:
            return self._finalize(WorkerResult(job.id, run_id, "busy", attempt, retry_of, self.worker_id))
        scratch = self._scratch_path(job.id)
        heartbeat: _SyncHeartbeat | None = None
        result: WorkerResult
        try:
            if self._is_cancelled(run_id):
                result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
            else:
                scratch.mkdir(parents=True)
                self._put_run(run_id, "running", payload)
                if not self.heartbeat(run_id):
                    owned = False
                    result = WorkerResult(job.id, run_id, "lease_lost", attempt, retry_of, self.worker_id)
                else:
                    heartbeat = _SyncHeartbeat(self, run_id, self.heartbeat_interval_seconds)
                    heartbeat.start()
                    value = self._call_handler(job, scratch)
                    if inspect.isawaitable(value):
                        if inspect.iscoroutine(value):
                            value.close()
                        raise TypeError("run_sync cannot execute an awaitable handler")
                    state = "lease_lost" if heartbeat.lost.is_set() else (
                        "cancelled" if self._is_cancelled(run_id) else "succeeded"
                    )
                    if state == "lease_lost":
                        owned = False
                    result = WorkerResult(job.id, run_id, state, attempt, retry_of, self.worker_id, value=value)
        except _LeaseLost:
            owned = False
            result = WorkerResult(job.id, run_id, "lease_lost", attempt, retry_of, self.worker_id)
        except Exception as exc:  # retry is represented by a new queue message
            result = WorkerResult(job.id, run_id, "failed", attempt, retry_of, self.worker_id, error=str(exc))
            if attempt <= self.max_retries:
                self.queue.enqueue(f"{job.id}:retry:{attempt}", {**payload, "attempt": attempt + 1, "retry_of": job.id})
        finally:
            if heartbeat is not None:
                heartbeat.stop()
            shutil.rmtree(scratch, ignore_errors=True)
            if owned and (heartbeat is None or not heartbeat.lost.is_set()):
                self.leases.release(run_id, self.worker_id)
        return self._finalize(result)

    async def _execute_async(self, job: Job) -> WorkerResult:
        payload = dict(job.payload)
        run_id = str(payload.get("run_id", job.id))
        retry_of = payload.get("retry_of")
        attempt = int(payload.get("attempt", 1))
        with self._state_lock:
            prior = self._finalized.get(job.id)
        if prior is not None:
            return prior
        owned, cancellation = await self._shield_and_drain(
            asyncio.to_thread(self.leases.acquire, run_id, self.worker_id, self.lease_ttl_seconds)
        )
        if cancellation is not None:
            cancelled_result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
            if owned:
                await self._shield_and_drain(asyncio.to_thread(self.leases.release, run_id, self.worker_id))
            finalized = await self._finalize_async(cancelled_result)
            del finalized
            raise cancellation
        if not owned:
            return await self._finalize_async(WorkerResult(job.id, run_id, "busy", attempt, retry_of, self.worker_id))

        scratch, cancel_error = await self._shield_and_drain(asyncio.to_thread(self._scratch_path, job.id))
        result: WorkerResult
        heartbeat_stop = asyncio.Event()
        heartbeat_task: asyncio.Task[bool] | None = None
        try:
            if cancel_error is not None or self._is_cancelled(run_id):
                result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
            else:
                _, operation_cancellation = await self._shield_and_drain(
                    asyncio.to_thread(scratch.mkdir, parents=True)
                )
                cancel_error = cancel_error or operation_cancellation
                _, operation_cancellation = await self._shield_and_drain(
                    asyncio.to_thread(self._put_run, run_id, "running", payload)
                )
                cancel_error = cancel_error or operation_cancellation
                renewed, operation_cancellation = await self._shield_and_drain(
                    asyncio.to_thread(self.heartbeat, run_id)
                )
                cancel_error = cancel_error or operation_cancellation
                if cancel_error is not None:
                    result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
                elif not renewed:
                    owned = False
                    result = WorkerResult(job.id, run_id, "lease_lost", attempt, retry_of, self.worker_id)
                else:
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(run_id, heartbeat_stop))
                    handler_result, operation_cancellation = await self._shield_and_drain(
                        asyncio.to_thread(self._call_handler, job, scratch)
                    )
                    cancel_error = cancel_error or operation_cancellation
                    if cancel_error is not None:
                        result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
                    elif inspect.isawaitable(handler_result):
                        value = await self._await_handler_with_heartbeat(handler_result, heartbeat_task)
                        lease_lost = heartbeat_task.done() and heartbeat_task.result() is False
                        if lease_lost:
                            owned = False
                            result = WorkerResult(job.id, run_id, "lease_lost", attempt, retry_of, self.worker_id)
                        else:
                            result = WorkerResult(
                                job.id,
                                run_id,
                                "cancelled" if self._is_cancelled(run_id) else "succeeded",
                                attempt,
                                retry_of,
                                self.worker_id,
                                value=value,
                            )
                    else:
                        lease_lost = heartbeat_task.done() and heartbeat_task.result() is False
                        if lease_lost:
                            owned = False
                        result = WorkerResult(
                            job.id,
                            run_id,
                            "lease_lost" if lease_lost else ("cancelled" if self._is_cancelled(run_id) else "succeeded"),
                            attempt,
                            retry_of,
                            self.worker_id,
                            value=handler_result,
                        )
        except _LeaseLost:
            owned = False
            result = WorkerResult(job.id, run_id, "lease_lost", attempt, retry_of, self.worker_id)
        except asyncio.CancelledError as cancellation:
            cancel_error = cancel_error or cancellation
            result = WorkerResult(job.id, run_id, "cancelled", attempt, retry_of, self.worker_id)
        except Exception as exc:
            result = WorkerResult(job.id, run_id, "failed", attempt, retry_of, self.worker_id, error=str(exc))
            if attempt <= self.max_retries:
                _, operation_cancellation = await self._shield_and_drain(
                    asyncio.to_thread(
                        self.queue.enqueue,
                        f"{job.id}:retry:{attempt}",
                        {**payload, "attempt": attempt + 1, "retry_of": job.id},
                    )
                )
                cancel_error = cancel_error or operation_cancellation
        finally:
            heartbeat_stop.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            _, operation_cancellation = await self._shield_and_drain(
                asyncio.to_thread(shutil.rmtree, scratch, ignore_errors=True)
            )
            cancel_error = cancel_error or operation_cancellation
            if owned:
                _, operation_cancellation = await self._shield_and_drain(
                    asyncio.to_thread(self.leases.release, run_id, self.worker_id)
                )
                cancel_error = cancel_error or operation_cancellation
        finalized = await self._finalize_async(result)
        if cancel_error is not None:
            raise cancel_error
        return finalized

    async def _heartbeat_loop(self, run_id: str, stop: asyncio.Event) -> bool:
        """Renew a lease until the operation finishes; False means ownership was lost."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_interval_seconds)
            except TimeoutError:
                try:
                    renewed = await asyncio.to_thread(self.heartbeat, run_id)
                except Exception:
                    return False
                if not renewed:
                    return False
        return True

    async def _await_handler_with_heartbeat(
        self, handler_result: Awaitable[Any], heartbeat_task: asyncio.Task[bool]
    ) -> Any:
        handler_task = asyncio.ensure_future(handler_result)
        done, _ = await asyncio.wait({handler_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED)
        if heartbeat_task in done and heartbeat_task.result() is False:
            handler_task.cancel()
            await asyncio.gather(handler_task, return_exceptions=True)
            raise _LeaseLost("worker lease was lost while the job was running")
        return await handler_task

    async def _shield_and_drain(
        self, awaitable: Awaitable[Any]
    ) -> tuple[Any, asyncio.CancelledError | None]:
        """Await an operation without abandoning its side effects on cancellation."""
        task = asyncio.ensure_future(awaitable)
        value: Any = None
        try:
            value = await asyncio.shield(task)
            return value, None
        except asyncio.CancelledError as cancellation:
            # The operation owns lifecycle side effects.  Drain it fully, but
            # never turn an operation failure into a normal cancellation.
            while not task.done():
                try:
                    value = await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            value = task.result()
            return value, cancellation

    async def _finalize_async(self, result: WorkerResult) -> WorkerResult:
        finalization_task = asyncio.create_task(self._finalize_async_inner(result))
        try:
            return await asyncio.shield(finalization_task)
        except asyncio.CancelledError:
            # Finalization is a transaction: wait for all side effects,
            # including ack and cache insertion, before propagating cancel.
            return_value = await finalization_task
            del return_value
            raise

    async def _finalize_async_inner(self, result: WorkerResult) -> WorkerResult:
        prior = await asyncio.to_thread(self._claim_finalization, result.job_id)
        if prior is not None:
            return prior
        try:
            finalizer_completed = await asyncio.to_thread(self._durable_finalizer_completed, result)
            if self.run_store is not None:
                await asyncio.to_thread(
                    self._put_run,
                    result.run_id,
                    result.state,
                    {
                        "job_id": result.job_id,
                        "error": result.error or "",
                        "finalizer_completed": finalizer_completed or self.finalizer is None,
                    },
                )
            with self._state_lock:
                finalizer_completed = finalizer_completed or result.job_id in self._finalizer_completed
            if self.finalizer is not None and result.state != "lease_lost" and not finalizer_completed:
                finalized = await asyncio.to_thread(self.finalizer, result)
                if inspect.isawaitable(finalized):
                    await finalized
                with self._state_lock:
                    self._finalizer_completed.add(result.job_id)
                await asyncio.to_thread(
                    self._put_run,
                    result.run_id,
                    result.state,
                    {"job_id": result.job_id, "error": result.error or "", "finalizer_completed": True},
                )
            if result.state in {"succeeded", "cancelled", "failed", "busy"}:
                acked = await asyncio.to_thread(self.queue.ack, result.job_id, self.worker_id)
                if not acked:
                    raise RuntimeError(f"ack failed for job {result.job_id}")
        except BaseException:
            self._release_finalization(result.job_id)
            raise
        self._release_finalization(result.job_id, result)
        return result

    def _is_cancelled(self, run_id: str) -> bool:
        with self._state_lock:
            if run_id in self._cancelled:
                return True
        if self.run_store is not None:
            try:
                run = self.run_store.get(run_id)
            except (AttributeError, OSError):
                run = None
            if run is not None and run.status == "cancelled":
                return True
        is_cancelled = getattr(self.queue, "is_cancelled", None)
        return bool(callable(is_cancelled) and is_cancelled(run_id))

    def _scratch_path(self, job_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", job_id).strip(".") or "job"
        scratch = self.scratch_parent / f".worker-{safe_id}-{uuid.uuid4().hex}"
        try:
            scratch.relative_to(self.scratch_parent)
        except ValueError as exc:
            raise ValueError("scratch path escapes scratch_parent") from exc
        return scratch

    def _call_handler(self, job: Job, scratch: Path) -> Any:
        signature = inspect.signature(self.handler)
        if len(signature.parameters) >= 2:
            return self.handler(job, scratch)
        return self.handler(job)

    def _put_run(self, run_id: str, status: str, payload: Mapping[str, Any]) -> None:
        if self.run_store is not None:
            self.run_store.put(Run(run_id, status=status, payload=dict(payload)))

    def _finalize(self, result: WorkerResult) -> WorkerResult:
        prior = self._claim_finalization(result.job_id)
        if prior is not None:
            return prior
        try:
            finalizer_completed = self._durable_finalizer_completed(result)
            if self.run_store is not None:
                self._put_run(
                    result.run_id,
                    result.state,
                    {
                        "job_id": result.job_id,
                        "error": result.error or "",
                        "finalizer_completed": finalizer_completed or self.finalizer is None,
                    },
                )
            with self._state_lock:
                finalizer_completed = finalizer_completed or result.job_id in self._finalizer_completed
            if self.finalizer is not None and result.state != "lease_lost" and not finalizer_completed:
                finalized = self.finalizer(result)
                if inspect.isawaitable(finalized):
                    if inspect.iscoroutine(finalized):
                        finalized.close()
                    raise TypeError("run_sync cannot execute an awaitable finalizer")
                with self._state_lock:
                    self._finalizer_completed.add(result.job_id)
                self._put_run(
                    result.run_id,
                    result.state,
                    {"job_id": result.job_id, "error": result.error or "", "finalizer_completed": True},
                )
            if result.state in {"succeeded", "cancelled", "failed", "busy"} and not self.queue.ack(
                result.job_id, self.worker_id
            ):
                raise RuntimeError(f"ack failed for job {result.job_id}")
        except BaseException:
            self._release_finalization(result.job_id)
            raise
        self._release_finalization(result.job_id, result)
        return result

    def _durable_finalizer_completed(self, result: WorkerResult) -> bool:
        if self.run_store is None:
            return False
        try:
            run = self.run_store.get(result.run_id)
        except Exception:
            return False
        payload = getattr(run, "payload", {}) if run is not None else {}
        return (
            isinstance(payload, Mapping)
            and payload.get("job_id") == result.job_id
            and payload.get("finalizer_completed") is True
        )

    def _claim_finalization(self, job_id: str) -> WorkerResult | None:
        with self._finalization_condition:
            while True:
                prior = self._finalized.get(job_id)
                if prior is not None:
                    return prior
                if job_id not in self._finalizing:
                    self._finalizing.add(job_id)
                    return None
                self._finalization_condition.wait()

    def _release_finalization(self, job_id: str, result: WorkerResult | None = None) -> None:
        with self._finalization_condition:
            if result is not None:
                self._finalized[job_id] = result
            self._finalizing.discard(job_id)
            self._finalization_condition.notify_all()
