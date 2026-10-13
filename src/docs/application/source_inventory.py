"""Canonical inventory of a document's sources: raw files waiting in the inbox plus converted ones."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.application.ingest_names import HARNESS_ARTIFACT_NAMES


def list_document_sources(doc_root: Path, paths: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return `{name, path, state}` for every inbox source (`inbox`) and ingested output (`ingested`).

    The classification queue only knows sources that have already been ingested, so it cannot answer
    "does this document have sources?"; this does, from the files themselves.  Paths are relative to
    `doc_root`; harness bookkeeping files, `_`-prefixed files and the verbatim `assets/` folder are not sources.
    """
    root = doc_root.resolve()
    inbox = Path(paths.get("inbox_dir", root / "inbox"))
    converted = Path(paths.get("sections_dir", root / "sections")) / "ingested"
    found: list[dict[str, str]] = []
    if inbox.is_dir():
        assets = inbox / "assets"
        for path in inbox.rglob("*"):
            if path.is_file() and assets not in path.parents and not _bookkeeping(path.name):
                found.append(_entry(root, path, "inbox"))
    if converted.is_dir():
        found.extend(
            _entry(root, path, "ingested") for path in converted.iterdir()
            if path.is_file() and not _bookkeeping(path.name)
        )
    return sorted(found, key=lambda item: (item["name"], item["path"]))


def _bookkeeping(name: str) -> bool:
    return name.startswith("_") or name in HARNESS_ARTIFACT_NAMES


def _entry(root: Path, path: Path, state: str) -> dict[str, str]:
    return {"name": path.name, "path": path.resolve().relative_to(root).as_posix(), "state": state}
