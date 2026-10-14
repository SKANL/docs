"""Run one or more durable local document jobs without starting the HTTP API."""

from __future__ import annotations

import argparse
from pathlib import Path

from .composition import RuntimeStores
from .domain.workspace_format import validate_workspace_layout, validate_workspace_marker
from .sidecar.worker import build_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process queued Doc Harness jobs for one workspace.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args(argv)
    root = args.workspace_root.expanduser().resolve()
    validate_workspace_layout(root, root / "documents", root / "templates")
    validate_workspace_marker(root)
    stores = RuntimeStores(root)
    runner = build_worker(
        root,
        stores.queue,
        stores.leases,
        stores.runs,
        stores.passports,
        stores.artifacts,
        stores.findings,
        stores.publications,
    )
    runner.run_until_stopped(args.iterations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
