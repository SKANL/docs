"""The single wall-clock stamp for authored provenance (stamp, revise).

The one wall-clock stamp: same value the CLI writes (`datetime.now().isoformat(timespec="seconds")`), so
a section stamped over HTTP, the worker, or the shell carries one format.
"""

from __future__ import annotations

from datetime import datetime


def authoring_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")
