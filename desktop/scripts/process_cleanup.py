"""Terminate a sidecar and every worker child it owns during test cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def terminate_process_tree(process: Any, *, timeout: float = 10.0) -> None:
    """Stop a spawned sidecar without leaving multiprocessing workers behind."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)
