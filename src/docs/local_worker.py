"""Run one or more durable local document jobs without starting the HTTP API."""

from __future__ import annotations

import argparse
from pathlib import Path

from .infrastructure.persistence.x20 import (
    SqliteArtifactStore,
    SqliteFindingStore,
    SqliteJobQueue,
    SqlitePassportStore,
    SqlitePublicationStore,
    SqliteRunStore,
)
from .sidecar import _build_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process queued Doc Harness jobs for one workspace.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args(argv)
    root = args.workspace_root.expanduser().resolve()
    state = root / ".docs" / "x20.sqlite3"
    queue = SqliteJobQueue(state)
    run_store = SqliteRunStore(state)
    passport_store = SqlitePassportStore(state)
    artifact_store = SqliteArtifactStore(state)
    findings_store = SqliteFindingStore(state)
    publication_store = SqlitePublicationStore(state)
    runner = _build_worker(
        root,
        queue,
        state,
        run_store,
        passport_store,
        artifact_store,
        findings_store,
        publication_store,
    )
    runner.run_until_stopped(args.iterations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
