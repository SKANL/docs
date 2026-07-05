# src/docs/application/ingest.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.ports.source_type_detector_port import SourceTypeDetectorPort

_DETECTION_REPORT_NAME = "_detection.json"


class IngestService:
    """Detects, routes, and ingests source files from an inbox directory into
    deterministic Markdown under `sections/ingested/` (document-ingest spec:
    `File-Type Detection`, `Type-Based Ingest Routing`, `Deterministic and
    Idempotent Ingest`, `Tool-Failure Reporting`). Unsupported/unrouted types
    are reported as `status: "unsupported"`; any exception raised during
    detect/read/ingest for a given file is caught and reported as
    `status: "error"` with a `cause` field — never raised, never batch-fatal
    (`Empty inbox` / unsupported-type / per-file-error scenarios)."""

    def __init__(
        self,
        detector: SourceTypeDetectorPort,
        handlers: dict[str, SourceIngestPort],
    ) -> None:
        self.detector = detector
        self.handlers = dict(handlers)

    def ingest_inbox(self, inbox_dir: Path, sections_dir: Path) -> dict[str, Any]:
        inbox_dir = Path(inbox_dir)
        sections_dir = Path(sections_dir)
        entries: list[dict[str, Any]] = []
        if inbox_dir.is_dir():
            # "_"-prefixed files (e.g. our own `_detection.json` report from a
            # prior run) are harness-internal, not sources — skip them, same
            # convention as `read_context_texts`.
            sources = sorted(
                path
                for path in inbox_dir.iterdir()
                if path.is_file() and not path.name.startswith("_")
            )
            entries = [self._ingest_one_safely(path, sections_dir) for path in sources]
        report = {"processed": len(entries), "files": entries}
        self._write_detection_report(inbox_dir, report)
        return report

    def _ingest_one_safely(self, src: Path, sections_dir: Path) -> dict[str, Any]:
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
        kind = ""
        try:
            kind = self.detector.detect(src)
            return self._ingest_one(src, sections_dir, kind)
        except Exception as exc:
            return {"file": src.name, "kind": kind or "unknown", "status": "error", "cause": str(exc)}

    def _ingest_one(self, src: Path, sections_dir: Path, kind: str) -> dict[str, Any]:
        sha256 = sha256_hex(src.read_bytes())
        handler = self.handlers.get(kind)
        if handler is None:
            return {
                "file": src.name,
                "kind": kind or "unknown",
                "status": "unsupported",
                "sha256": sha256,
            }
        ingested_dir = sections_dir / "ingested"
        existing = self._existing_output(ingested_dir, src.stem, kind, sha256[:8])
        if existing is not None:
            return {
                "file": src.name,
                "kind": kind,
                "status": "skipped",
                "sha256": sha256,
                "output": str(existing),
            }
        ingested_dir.mkdir(parents=True, exist_ok=True)
        output = handler.ingest(src, ingested_dir, kind)
        return {
            "file": src.name,
            "kind": kind,
            "status": "ingested",
            "sha256": sha256,
            "output": str(output),
        }

    def _existing_output(self, ingested_dir: Path, stem: str, kind: str, sha8: str) -> Path | None:
        # Identity is (stem, kind, content hash), not just (stem, hash): two
        # files with the same stem and byte-identical bodies but different
        # detected kinds (e.g. readme.md / readme.txt) are distinct sources
        # and must not collide on the same output path (fresh-review fix —
        # a `stem+sha8`-only key silently skipped the second file's handler).
        candidate = ingested_output_path(ingested_dir, stem, kind, sha8)
        return candidate if candidate.exists() else None

    def _write_detection_report(self, inbox_dir: Path, report: dict[str, Any]) -> None:
        if not inbox_dir.is_dir():
            return
        detection_path = inbox_dir / _DETECTION_REPORT_NAME
        # Deterministic: stable key ordering, no timestamps or randomness.
        detection_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
