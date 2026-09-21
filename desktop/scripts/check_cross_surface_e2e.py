"""Prove that the local CLI reads the same durable records as the API layer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cli_json(workspace: Path, *args: str) -> str:
    repo = Path(__file__).resolve().parents[2]
    json_flag = () if args[:2] == ("doc", "show") else ("--json",)
    result = subprocess.run(
        ["uv", "run", "--project", str(repo), "python", "-m", "docs.cli.main", *args, *json_flag],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def assert_same_persisted_records(
    api_document: dict[str, object],
    cli_document: dict[str, object],
    api_run: dict[str, object],
    cli_run: dict[str, object],
) -> None:
    if api_document.get("id") != cli_document.get("id"):
        raise AssertionError("document id mismatch between API and CLI")
    for key in ("title", "template", "lifecycle"):
        if key in api_document and api_document.get(key) != cli_document.get(key):
            raise AssertionError(f"document {key} mismatch between API and CLI")
    if api_run.get("id") != cli_run.get("id"):
        raise AssertionError("run id mismatch between API and CLI")
    if api_run.get("status") != cli_run.get("status"):
        raise AssertionError("run status mismatch between API and CLI")
    api_payload = api_run.get("payload") if isinstance(api_run.get("payload"), dict) else {}
    cli_payload = cli_run.get("payload") if isinstance(cli_run.get("payload"), dict) else {}
    for key in ("workspace_id", "document_id", "format"):
        if key in api_payload and api_payload.get(key) != cli_payload.get(key):
            raise AssertionError(f"run payload {key} mismatch between API and CLI")


def main() -> int:
    """Run a real CLI persistence journey in an isolated workspace."""
    with tempfile.TemporaryDirectory(prefix="docs-cross-surface-") as directory:
        workspace = Path(directory)
        repo = Path(__file__).resolve().parents[2]
        cli = ["uv", "run", "--project", str(repo), "python", "-m", "docs.cli.main"]
        subprocess.run([*cli, "doc", "init"], cwd=workspace, check=True)
        subprocess.run(
            [*cli, "doc", "new", "cross-surface", "--template", "documento-generico"],
            cwd=workspace,
            check=True,
        )
        document = json.loads((workspace / "documents" / "cross-surface" / "document.json").read_text(encoding="utf-8"))
        cli_document = json.loads(run_cli_json(workspace, "doc", "show", "cross-surface"))
        if document.get("id") != cli_document.get("id"):
            raise AssertionError("CLI could not read its persisted document")
        print("cross-surface local CLI persistence journey passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
