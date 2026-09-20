"""Dependency-injected command-line entry point for document workers."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NoReturn

from docs.workers.runner import WorkerRunner
from docs.workers.service import WorkerService

SUCCESS = 0
RUNTIME_FAILURE = 1
USAGE_OR_CONFIGURATION_ERROR = 2
INTERRUPTED = 130


@dataclass(frozen=True)
class WorkerConfiguration:
    """Runtime settings passed to an application's worker-service factory."""

    iterations: int | None
    poll_interval: float
    backoff: float
    worker_id: str | None


WorkerServiceFactory = Callable[[WorkerConfiguration], WorkerService]


class _Parser(argparse.ArgumentParser):
    """An argument parser whose errors are returned by :func:`main`."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _non_negative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _finite_non_negative(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def _finite_backoff(value: str) -> float:
    parsed = _finite_non_negative(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a finite number of at least one")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Run an already-configured document worker.")
    parser.add_argument(
        "--iterations",
        type=_non_negative_integer,
        default=None,
        help="Maximum polls to run; omit to run until interrupted.",
    )
    parser.add_argument(
        "--poll-interval",
        type=_finite_non_negative,
        default=1.0,
        help="Seconds to wait after the first idle poll (default: 1.0).",
    )
    parser.add_argument(
        "--backoff",
        type=_finite_backoff,
        default=1.0,
        help="Idle-poll wait multiplier (default: 1.0).",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="Worker identity for the service factory to configure.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: WorkerServiceFactory | None = None,
) -> int:
    """Run a worker service made available by an application's factory.

    Applications supply queue, lease, handler, and any persistence adapters in
    ``service_factory``. This module deliberately supplies none of them.
    """
    parser = _build_parser()
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else USAGE_OR_CONFIGURATION_ERROR
    except ValueError as exc:
        parser.print_usage(sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return USAGE_OR_CONFIGURATION_ERROR

    configuration = WorkerConfiguration(
        iterations=options.iterations,
        poll_interval=options.poll_interval,
        backoff=options.backoff,
        worker_id=options.worker_id,
    )
    if service_factory is None:
        print("error: a WorkerService factory must be supplied by the application", file=sys.stderr)
        return USAGE_OR_CONFIGURATION_ERROR

    try:
        service = service_factory(configuration)
    except KeyboardInterrupt:
        return INTERRUPTED
    except Exception as exc:
        print(f"error: worker configuration failed: {exc}", file=sys.stderr)
        return USAGE_OR_CONFIGURATION_ERROR

    runner: WorkerRunner | None = None
    try:
        runner = WorkerRunner(
            service,
            poll_interval=configuration.poll_interval,
            backoff=configuration.backoff,
        )
        with runner:
            runner.run_until_stopped(configuration.iterations)
    except KeyboardInterrupt:
        if runner is not None:
            runner.stop()
        return INTERRUPTED
    except Exception as exc:
        print(f"error: worker execution failed: {exc}", file=sys.stderr)
        return RUNTIME_FAILURE
    return SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
