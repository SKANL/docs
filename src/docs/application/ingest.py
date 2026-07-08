# src/docs/application/ingest.py
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.ports.source_type_detector_port import SourceTypeDetectorPort

_DETECTION_REPORT_NAME = "_detection.json"
_SOURCE_MANIFEST_NAME = "_source-manifest.json"

# `inbox/assets/` is the verbatim-asset convention (design.md Decision 6) --
# excluded from the recursive source walk entirely (routed elsewhere, not a
# markdown-ingest concern), but its presence is still reported (never
# silently skipped) via the `ignored` field.
_ASSETS_DIR_NAME = "assets"

# Content-addressed media-dir shape (document-ingest spec: "Orphan Media
# Directory Cleanup"; design.md Decision 8 #13): pandoc's
# `--extract-media=<stem>-<kind>-<sha8>_media` (PandocIngestAdapter) always
# produces a dirname whose base (before `_media`) ends in a hyphen plus
# exactly 8 lowercase hex chars -- the same `sha256_hex(...)[:8]` used for
# the paired `.md` output's own identity. A dirname that does NOT match this
# shape was never produced by this harness and must never be touched.
_CONTENT_ADDRESSED_MEDIA_RE = re.compile(r"^(?P<base>.+-[0-9a-f]{8})_media$")

# Hardened (fresh-context verify, PR2 fix batch, WARNING-1): a directory NAME
# matching the content-addressed shape is not, by itself, proof its CONTENTS
# are genuinely pandoc-extracted media -- a human could add a file to a
# directory the harness legitimately created and later orphans. Every file
# (recursively, since pandoc may nest under a `media/` subfolder) must have
# one of these extensions or the WHOLE directory is refused, never
# partial-deleted.
_EXPECTED_MEDIA_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".svg", ".emf", ".wmf", ".webp"}
)


def _relposix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _has_underscore_component(relative_posix: str) -> bool:
    return any(part.startswith("_") for part in relative_posix.split("/"))


def _is_under_assets(relative_posix: str) -> bool:
    return relative_posix.split("/", 1)[0] == _ASSETS_DIR_NAME


class _InlineJsonWriter:
    """Default `IngestArtifactWriter` used when the composition root does
    not inject one -- preserves `IngestService`'s pre-Front-C constructor
    ergonomics (dozens of existing unit tests construct it with just a
    detector + handlers) without `application/ingest.py` importing an
    `infrastructure/` adapter (dependency-direction rule: cli -> application
    -> domain; infrastructure implements domain ports, never the reverse).
    NOT atomic -- the real `FilesystemIngestArtifactWriter` (wired in
    `cli/_shared.py` `Deps.__init__`, design.md Decision 9) is; this
    fallback exists only so `IngestService` stays usable standalone."""

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )


class IngestService:
    """Detects, routes, and ingests source files from an inbox directory
    (recursively — document-ingest spec: `Recursive Inbox Scan with
    Provenance`) into deterministic Markdown under `sections/ingested/`
    (spec: `File-Type Detection`, `Type-Based Ingest Routing`,
    `Deterministic and Idempotent Ingest`, `Tool-Failure Reporting`).
    Unsupported/unrouted types are reported as `status: "unsupported"`; any
    exception raised during detect/read/ingest for a given file is caught
    and reported as `status: "error"` with a `cause` field — never raised,
    never batch-fatal (`Empty inbox` / unsupported-type / per-file-error
    scenarios). Identity stays `<stem>-<kind>-<sha8>.md` (content-hash only)
    regardless of how deep a source lives in the tree — the subfolder is
    reported as `relative_path`/`source_dir` provenance metadata, never
    identity (design.md Decision 2)."""

    def __init__(
        self,
        detector: SourceTypeDetectorPort,
        handlers: dict[str, SourceIngestPort],
        writer: IngestArtifactWriter | None = None,
    ) -> None:
        self.detector = detector
        self.handlers = dict(handlers)
        self.writer: IngestArtifactWriter = writer or _InlineJsonWriter()

    def ingest_inbox(self, inbox_dir: Path, sections_dir: Path) -> dict[str, Any]:
        inbox_dir = Path(inbox_dir)
        sections_dir = Path(sections_dir)
        entries: list[dict[str, Any]] = []
        ignored: list[dict[str, str]] = []
        if inbox_dir.is_dir():
            sources, ignored, empty_dir_entries = self._walk_inbox(inbox_dir)
            # Pre-scan snapshot (design.md Decision 3): captured ONCE, before
            # any conversion this scan, so status resolution can distinguish
            # "already present from a prior run" (skipped) from "produced
            # during THIS scan by something else" (batched) -- whether that
            # "something else" is a JVM look-ahead batch sibling or simply an
            # earlier byte-identical source reached first in sort order.
            existing_before = self._snapshot_ingested_outputs(sections_dir / "ingested")
            entries = [
                self._ingest_one_safely(path, relative_path, sections_dir, existing_before)
                for path, relative_path in sources
            ]
            entries.extend(empty_dir_entries)
            entries.sort(key=lambda entry: entry["relative_path"])
            self._write_source_manifest(inbox_dir, entries)
        report = {
            "processed": sum(1 for e in entries if e.get("status") != "empty_dir"),
            "files": entries,
            "ignored": ignored,
            "media_cleanup": self._clean_orphan_media(sections_dir / "ingested"),
        }
        self._write_detection_report(inbox_dir, report)
        return report

    def _walk_inbox(
        self, inbox_dir: Path
    ) -> tuple[list[tuple[Path, str]], list[dict[str, str]], list[dict[str, str]]]:
        # Recursive, deterministically-ordered walk (design.md Decision 2):
        # `rglob("*")` results are filtered then manually sorted by the
        # POSIX relative-path string -- the sort key, not the filesystem
        # walker, owns cross-platform determinism. `_`-prefixed components
        # (anywhere in the tree, extending the pre-existing top-level rule)
        # and the whole `inbox/assets/` subtree (Decision 6) are excluded
        # from the source walk but reported under `ignored`, never silent.
        all_paths = sorted(inbox_dir.rglob("*"), key=lambda p: _relposix(p, inbox_dir))
        files = [p for p in all_paths if p.is_file()]
        dirs = [p for p in all_paths if p.is_dir()]

        sources: list[tuple[Path, str]] = []
        ignored: list[dict[str, str]] = []
        for path in files:
            rel = _relposix(path, inbox_dir)
            if _has_underscore_component(rel):
                ignored.append({"relative_path": rel, "reason": "underscore_prefixed"})
                continue
            if _is_under_assets(rel):
                ignored.append({"relative_path": rel, "reason": "assets_subtree"})
                continue
            sources.append((path, rel))

        empty_dir_entries = self._find_empty_dirs(inbox_dir, dirs, {rel for _, rel in sources})
        return sources, ignored, empty_dir_entries

    def _find_empty_dirs(
        self, inbox_dir: Path, dirs: list[Path], source_relatives: set[str]
    ) -> list[dict[str, str]]:
        # A directory (excluding `_`-prefixed and `assets/`) with zero
        # eligible source files anywhere beneath it is reported as
        # `{"relative_path": "<dir>/", "status": "empty_dir"}` — never
        # silent (design.md Decision 2). A chain of nested empty
        # subdirectories collapses to just the OUTERMOST empty one, so a
        # totally-empty subtree produces one honest marker, not one per
        # level.
        eligible: list[str] = []
        for d in dirs:
            rel = _relposix(d, inbox_dir)
            if _has_underscore_component(rel) or _is_under_assets(rel):
                continue
            eligible.append(rel)
        eligible.sort()

        empty_entries: list[dict[str, str]] = []
        reported_prefixes: list[str] = []
        for rel in eligible:
            has_source = any(s == rel or s.startswith(rel + "/") for s in source_relatives)
            if has_source:
                continue
            if any(rel == prefix or rel.startswith(prefix + "/") for prefix in reported_prefixes):
                continue  # nested inside an already-reported empty ancestor
            empty_entries.append({"relative_path": rel + "/", "status": "empty_dir"})
            reported_prefixes.append(rel)
        return empty_entries

    def _snapshot_ingested_outputs(self, ingested_dir: Path) -> set[Path]:
        if not ingested_dir.is_dir():
            return set()
        return {p for p in ingested_dir.iterdir() if p.is_file()}

    def _ingest_one_safely(
        self, src: Path, relative_path: str, sections_dir: Path, existing_before: set[Path]
    ) -> dict[str, Any]:
        # A single unreadable/vanished file or a failing handler must not
        # abort the whole scan (fresh-review fix, scoped narrowly): any
        # exception from detect/read/ingest is caught, reported with its
        # cause, and the scan continues so `_detection.json` always reflects
        # everything scanned. This is distinct from PR6 task 6.3's configured
        # fail-fast for real per-type adapters, which this does not implement.
        # Detection runs outside the inner try so a kind resolved before a
        # later failure (e.g. the handler itself raising) survives into the
        # error entry instead of being reported as "unknown" (PR6 fresh-review
        # carry-forward (b) — detection succeeding is independent evidence
        # from ingestion succeeding).
        source_dir = str(Path(relative_path).parent.as_posix())
        if source_dir == ".":
            source_dir = ""
        kind = ""
        try:
            kind = self.detector.detect(src)
            return self._ingest_one(src, relative_path, source_dir, sections_dir, kind, existing_before)
        except Exception as exc:
            return {
                "file": src.name,
                "relative_path": relative_path,
                "source_dir": source_dir,
                "kind": kind or "unknown",
                "status": "error",
                "cause": str(exc),
            }

    def _ingest_one(
        self,
        src: Path,
        relative_path: str,
        source_dir: str,
        sections_dir: Path,
        kind: str,
        existing_before: set[Path],
    ) -> dict[str, Any]:
        sha256 = sha256_hex(src.read_bytes())
        entry_base = {
            "file": src.name,
            "relative_path": relative_path,
            "source_dir": source_dir,
            "kind": kind or "unknown",
        }
        handler = self.handlers.get(kind)
        if handler is None:
            return {**entry_base, "status": "unsupported", "sha256": sha256}

        ingested_dir = sections_dir / "ingested"
        candidate = ingested_output_path(ingested_dir, src.stem, kind, sha256[:8])
        status = self._resolve_conversion_status(candidate, existing_before)
        if status is not None:
            return {**entry_base, "status": status, "sha256": sha256, "output": str(candidate)}

        ingested_dir.mkdir(parents=True, exist_ok=True)
        output = handler.ingest(src, ingested_dir, kind)
        return {**entry_base, "status": "ingested", "sha256": sha256, "output": str(output)}

    def _resolve_conversion_status(self, candidate: Path, existing_before: set[Path]) -> str | None:
        # Status vocabulary (design.md Decision 3, resolves #12): resolved
        # purely against the PRE-SCAN snapshot, never a live existence check
        # alone -- so "produced by something else during this same scan"
        # (a JVM look-ahead batch sibling, or simply an earlier
        # byte-identical source reached first in sort order) is always
        # "batched", distinct from "already present from a prior run"
        # ("skipped"). Returns None when the file must actually be converted.
        if candidate in existing_before:
            return "skipped"
        if candidate.exists():
            return "batched"
        return None

    def _clean_orphan_media(self, ingested_dir: Path) -> dict[str, list[Any]]:
        # Runs as a step during every ingest scan (design.md Decision 8 #13;
        # spec: document-ingest "Orphan Media Directory Cleanup"). Only
        # content-addressed orphans are removed -- a `_media/` dir is deleted
        # ONLY if (a) its NAME matches the content-addressed shape, (b) no
        # current ingested `.md` output references it (i.e. the paired output
        # was removed, or re-ingesting the source produced a different
        # sha8), AND (c) every file inside it looks like pandoc-extracted
        # media (WARNING-1 hardening -- a name match alone is not proof of
        # content, so this fails toward refusal rather than partial-delete).
        # A per-item filesystem error (e.g. `rmtree` refusing to follow a
        # symlink, SUGGESTION-1) is caught and reported as refused too,
        # never aborting the rest of the scan. Every refusal carries a
        # `cause`; nothing is ever silently skipped. This scans the FLAT
        # `sections/ingested/` output directory, which recursion (Front C)
        # does not change -- output identity/layout is content-hash only,
        # never mirrors the inbox's folder structure.
        removed: list[str] = []
        refused: list[dict[str, str]] = []
        if ingested_dir.is_dir():
            media_dirs = sorted(
                path for path in ingested_dir.iterdir() if path.is_dir() and path.name.endswith("_media")
            )
            for media_dir in media_dirs:
                try:
                    match = _CONTENT_ADDRESSED_MEDIA_RE.match(media_dir.name)
                    if match is None:
                        refused.append(
                            {
                                "path": media_dir.name,
                                "cause": (
                                    "does not match the content-addressed "
                                    "<stem>-<kind>-<sha8>_media shape"
                                ),
                            }
                        )
                        continue
                    paired_md = ingested_dir / f"{match.group('base')}.md"
                    if paired_md.exists():
                        continue  # still referenced -- never delete
                    unexpected = self._first_unexpected_media_file(media_dir)
                    if unexpected is not None:
                        refused.append(
                            {
                                "path": media_dir.name,
                                "cause": (
                                    f"contains unexpected file `{unexpected}`, not recognized "
                                    "as pandoc-extracted media -- refusing the whole directory"
                                ),
                            }
                        )
                        continue
                    shutil.rmtree(media_dir)
                    removed.append(media_dir.name)
                except OSError as exc:
                    refused.append({"path": media_dir.name, "cause": f"filesystem error: {exc}"})
        return {"removed": removed, "refused": refused}

    def _first_unexpected_media_file(self, media_dir: Path) -> str | None:
        # Deterministic: sorted traversal, first offender wins (stable
        # regardless of filesystem iteration order).
        for path in sorted(media_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() not in _EXPECTED_MEDIA_EXTENSIONS:
                return path.relative_to(media_dir).as_posix()
        return None

    def _write_detection_report(self, inbox_dir: Path, report: dict[str, Any]) -> None:
        if not inbox_dir.is_dir():
            return
        # Atomic, deterministic write via the injected IngestArtifactWriter
        # port (design.md Decision 9) -- no direct write_text here anymore.
        self.writer.write_json(inbox_dir / _DETECTION_REPORT_NAME, report)

    def _write_source_manifest(self, inbox_dir: Path, entries: list[dict[str, Any]]) -> None:
        # `inbox/_source-manifest.json` (design.md's artifact map): distinct
        # from the collection stage's `sections/source-manifest.json`.
        # Ingest-time provenance only in this front (Front D/E later extend
        # these same entries with role/duplicate fields). `_`-prefixed, so
        # the recursive walk itself always skips it, same as
        # `_detection.json`.
        sources = [entry for entry in entries if entry.get("status") != "empty_dir"]
        payload = {"schema": 1, "sources": sources}
        self.writer.write_json(inbox_dir / _SOURCE_MANIFEST_NAME, payload)
