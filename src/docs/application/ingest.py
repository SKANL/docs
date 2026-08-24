# src/docs/application/ingest.py
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from docs.application.ingest_classification import SourceClassifier
from docs.application.ingest_figures import FigureIngestPipeline
from docs.application.ingest_names import (
    DETECTION_REPORT_NAME,
    HARNESS_ARTIFACT_NAMES,
    IMAGE_EXTENSIONS,
    INTAKE_REPORT_NAME,
    SOURCE_MANIFEST_NAME,
    VECTOR_EXTENSIONS,
    guess_asset_kind,
)
from docs.application.inline_json_writer import InlineJsonWriter
from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.intake_report import render_intake_report
from docs.domain.ports.content_probe_port import ContentProbePort
from docs.domain.ports.image_metadata_port import ImageMetadataPort
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.ports.pdf_render_port import PdfRenderPort
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.ports.source_type_detector_port import SourceTypeDetectorPort
from docs.domain.ports.svg_rasterizer_port import SvgRasterizerPort
from docs.domain.source_role import classify

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




def _is_heuristic_asset_candidate(relative_posix: str) -> bool:
    suffix = Path(relative_posix).suffix.lower()
    if suffix in IMAGE_EXTENSIONS or suffix in VECTOR_EXTENSIONS:
        return True
    return suffix == ".docx" and guess_asset_kind(relative_posix) is not None




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
        image_metadata: ImageMetadataPort | None = None,
        content_probe: ContentProbePort | None = None,
        pdf_render: PdfRenderPort | None = None,
        svg_rasterizer: SvgRasterizerPort | None = None,
    ) -> None:
        self.detector = detector
        self.handlers = dict(handlers)
        self.writer: IngestArtifactWriter = writer or InlineJsonWriter()
        self.image_metadata = image_metadata
        # Item D, PR4: optional, injected exactly like `image_metadata`
        # (design.md ADR-D) -- `None` degrades to folder/filename-only
        # classification, fail-open, never a hard dependency.
        self.content_probe = content_probe
        # Item F, PR5: optional, injected exactly like `content_probe`
        # (design.md ADR-F) -- `None` (toolchain unavailable) degrades to
        # "no rendered figures, WARN", never a hard dependency.
        self.pdf_render = pdf_render
        # HIGH silent-failure fix: optional, injected exactly like
        # `pdf_render` -- `None` (resvg absent) degrades a standalone
        # ingested `.svg` to WARN+skip (never cataloged), never a hard
        # dependency for the rest of ingest.
        self.svg_rasterizer = svg_rasterizer
        # Two collaborators, each owning one concern and the ports that serve
        # it. `IngestService` keeps detection/conversion/reporting and
        # delegates the rest -- it no longer holds 34 methods across four
        # unrelated jobs.
        self.classifier = SourceClassifier(self.writer)
        self.figures = FigureIngestPipeline(
            self.writer,
            self.classifier,
            image_metadata=image_metadata,
            pdf_render=pdf_render,
            svg_rasterizer=svg_rasterizer,
        )

    def ingest_inbox(
        self,
        inbox_dir: Path,
        sections_dir: Path,
        strict: bool = False,
        assets_dir: Path | None = None,
    ) -> dict[str, Any]:
        inbox_dir = Path(inbox_dir)
        sections_dir = Path(sections_dir)
        entries: list[dict[str, Any]] = []
        ignored: list[dict[str, str]] = []
        manifest_payload: dict[str, Any] = {
            "schema": 1,
            "sources": [],
            "duplicates": [],
            "placements": [],
            "conflicts": [],
        }
        if inbox_dir.is_dir():
            sources, ignored, empty_dir_entries, declared_assets, heuristic_candidates = (
                self._walk_inbox(inbox_dir)
            )
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

            # Front F (design.md Decision 6a): pre-ingest asset routing +
            # pending-placement queue, same external-confirmation contract
            # as the classification queue.
            placements = self.figures.route_and_queue_assets(
                inbox_dir, declared_assets, heuristic_candidates, assets_dir
            )
            self.figures.build_figure_catalog_for(
                inbox_dir, sections_dir, declared_assets, heuristic_candidates, entries, assets_dir
            )

            # Front D (design.md Decision 4): classify every real source
            # entry, merge any externally-confirmed role from the PRIOR
            # classification queue (the interface where confirmation
            # enters), resolve the draft/strict gate, then (re)write the
            # queue. Front E (Decision 5): near-duplicate pass over the
            # just-produced `ingested/` outputs, preserving any manual
            # kept/superseded reversal already recorded in the manifest.
            manifest_sources = self._build_manifest_sources(inbox_dir, entries, strict)
            self.classifier.write_classification_queue(inbox_dir, manifest_sources)
            duplicates = self.classifier.find_near_duplicates(inbox_dir, manifest_sources)
            # Item K (design.md ADR-K): a deterministic, curated-term-group
            # check over the just-produced ingested text -- WARN only, never
            # blocks, never auto-resolves (fail-open, agent decides).
            conflicts = self.classifier.detect_source_conflicts(manifest_sources)
            self.classifier.warn_conflicts(conflicts)
            manifest_payload = {
                "schema": 1,
                "sources": manifest_sources,
                "duplicates": duplicates,
                "placements": placements,
                "conflicts": [
                    {"group": c.group, "members": list(c.members), "sources": list(c.sources)}
                    for c in conflicts
                ],
            }
            self._write_source_manifest(inbox_dir, manifest_payload)
        report = {
            "processed": sum(1 for e in entries if e.get("status") != "empty_dir"),
            "files": entries,
            "ignored": ignored,
            "media_cleanup": self._clean_orphan_media(sections_dir / "ingested"),
        }
        self._write_detection_report(inbox_dir, report)
        # Item G (design.md ADR-G): a VIEW over already-produced artifacts,
        # never a new source of truth -- gap-report.json and
        # 00-fact-ledger.md may not exist yet on a first ingest pass
        # (built by later pipeline stages), so both reads are best-effort.
        self._write_intake_report(inbox_dir, sections_dir, report, manifest_payload)
        return report

    def _walk_inbox(self, inbox_dir: Path) -> tuple[
        list[tuple[Path, str]],
        list[dict[str, str]],
        list[dict[str, str]],
        list[tuple[Path, str]],
        list[tuple[Path, str]],
    ]:
        # Recursive, deterministically-ordered walk (design.md Decision 2):
        # `rglob("*")` results are filtered then manually sorted by the
        # POSIX relative-path string -- the sort key, not the filesystem
        # walker, owns cross-platform determinism. `_`-prefixed components
        # (anywhere in the tree, extending the pre-existing top-level rule)
        # and the whole `inbox/assets/` subtree (Decision 6) are excluded
        # from the source walk but reported under `ignored`, never silent.
        # PR3 verify follow-up (finding c, reader-facing note): sorting is
        # CASE-SENSITIVE (plain Python string `<`, ASCII byte order), NOT
        # locale-collated -- an uppercase-leading path sorts before an
        # all-lowercase one (e.g. "Report.md" before "archive.md"), which
        # can surprise a human skimming `_detection.json` expecting
        # conventional case-insensitive alphabetical order. This is
        # deliberate (design.md Decision 2): it is the only way Windows and
        # Linux agree on ordering without a locale-dependent collation.
        all_paths = sorted(inbox_dir.rglob("*"), key=lambda p: _relposix(p, inbox_dir))
        files = [p for p in all_paths if p.is_file()]
        dirs = [p for p in all_paths if p.is_dir()]

        sources: list[tuple[Path, str]] = []
        ignored: list[dict[str, str]] = []
        declared_assets: list[tuple[Path, str]] = []
        heuristic_candidates: list[tuple[Path, str]] = []
        for path in files:
            rel = _relposix(path, inbox_dir)
            if rel in HARNESS_ARTIFACT_NAMES:
                # PR3 verify follow-up (finding a): the harness's OWN
                # bookkeeping files get a DISTINCT reason from a genuine
                # user `_`-prefixed file, so a downstream/agent consumer can
                # mechanically filter them out without hardcoding filename
                # knowledge -- still reported, never silently dropped.
                ignored.append({"relative_path": rel, "reason": "harness_artifact"})
                continue
            if _has_underscore_component(rel):
                ignored.append({"relative_path": rel, "reason": "underscore_prefixed"})
                continue
            if _is_under_assets(rel):
                # design.md Decision 6a: anything under inbox/assets/ is a
                # DECLARED verbatim asset -- excluded from the source walk
                # (unchanged from Front C) but now also routed (Front F).
                ignored.append({"relative_path": rel, "reason": "assets_subtree"})
                declared_assets.append((path, rel))
                continue
            if _is_heuristic_asset_candidate(rel):
                # design.md Decision 6a: a likely verbatim asset (image
                # anywhere, or a cover/portada/anexo-visual-signaled .docx)
                # is excluded from markdown ingest -- it must never be
                # flattened to markdown before a human confirms it either
                # way -- but reported (never silently dropped) and proposed
                # to the placement queue. "Not auto-routed" (design.md)
                # means not auto-COPIED into asset storage without
                # confirmation, not "still ingested as regular content".
                ignored.append({"relative_path": rel, "reason": "asset_candidate"})
                heuristic_candidates.append((path, rel))
                continue
            sources.append((path, rel))

        asset_relatives = {rel for _, rel in (*declared_assets, *heuristic_candidates)}
        empty_dir_entries = self._find_empty_dirs(
            inbox_dir, dirs, {rel for _, rel in sources} | asset_relatives
        )
        return sources, ignored, empty_dir_entries, declared_assets, heuristic_candidates

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
        self.writer.write_json(inbox_dir / DETECTION_REPORT_NAME, report)

    def _write_source_manifest(self, inbox_dir: Path, payload: dict[str, Any]) -> None:
        # `inbox/_source-manifest.json` (design.md's artifact map): distinct
        # from the collection stage's `sections/source-manifest.json`.
        # `_`-prefixed, so the recursive walk itself always skips it, same
        # as `_detection.json`. `payload` already carries schema/sources/
        # duplicates/placements/conflicts -- built by the caller so it can
        # be reused verbatim by `_write_intake_report` (item G).
        self.writer.write_json(inbox_dir / SOURCE_MANIFEST_NAME, payload)

    # --- Front D: source-role classification (design.md Decision 4) -----

    def _build_manifest_sources(
        self, inbox_dir: Path, entries: list[dict[str, Any]], strict: bool
    ) -> list[dict[str, Any]]:
        # Classification is a PURE function of relative_path (+ optional
        # already-probed content signals) -- zero AI judgment, zero I/O,
        # zero randomness at runtime (spec: document-ingest "Source-Role
        # Classification" / item D "Content-Based Source Classification").
        # External confirmation enters ONLY through the classification
        # queue file (an agent/human edits it); a prior confirmation
        # round-trips forward into this run's manifest AND the
        # freshly-rewritten queue.
        prior_confirmed = self.classifier.read_prior_confirmed_roles(inbox_dir)
        sources: list[dict[str, Any]] = []
        for entry in entries:
            if entry.get("status") == "empty_dir":
                continue
            relative_path = entry["relative_path"]
            signals = self._probe_content(inbox_dir, relative_path)
            role, confidence, role_signals = classify(relative_path, signals=signals)
            confirmed_role = prior_confirmed.get(relative_path)
            manifest_entry = dict(entry)
            manifest_entry["proposed_role"] = role
            manifest_entry["confidence"] = confidence
            manifest_entry["signals"] = role_signals
            manifest_entry["confirmed_role"] = confirmed_role
            manifest_entry["role_status"] = self.classifier.resolve_role_gate(
                role, confidence, confirmed_role, strict
            )
            sources.append(manifest_entry)
        return sources

    def _probe_content(self, inbox_dir: Path, relative_path: str) -> Any:
        # I/O lives here (application layer, injected adapter), never in
        # the pure domain classifier (ADR-D "Signals-as-strings boundary").
        # No probe wired -> None, degrading to folder/filename-only
        # classification exactly as before PR4 (fail-open).
        if self.content_probe is None:
            return None
        return self.content_probe.probe(inbox_dir / relative_path)




    # --- Front E: near-duplicate detection (design.md Decision 5) -------



    # --- Item K: cross-source conflict detection (design.md ADR-K) --------



    # --- Item G: intake / gap report (design.md ADR-G) --------------------

    def _read_gap_report(self, sections_dir: Path) -> dict[str, Any]:
        gap_path = Path(sections_dir) / "gap-report.json"
        if not gap_path.exists():
            return {}
        try:
            return json.loads(gap_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _read_ledger_pending(self, sections_dir: Path) -> list[str]:
        ledger_path = Path(sections_dir) / "00-fact-ledger.md"
        if not ledger_path.exists():
            return []
        pending: list[str] = []
        for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "PENDIENTE" in line:
                pending.append(line.lstrip("-* ").strip())
        return pending

    def _write_intake_report(
        self,
        inbox_dir: Path,
        sections_dir: Path,
        detection: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        if not inbox_dir.is_dir():
            return
        gap_report = self._read_gap_report(sections_dir)
        ledger_pending = self._read_ledger_pending(sections_dir)
        content = render_intake_report(detection, manifest, gap_report, ledger_pending)
        (inbox_dir / INTAKE_REPORT_NAME).write_text(content, encoding="utf-8")

    # --- Front F: verbatim assets + placement queue (design.md Decision 6a)




    # --- Front F: figure catalog (design.md Decision 6b) -----------------
    #
    # S0.2 (smart-figure-embedding): today's `inbox/` intake only ever
    # presents a figure candidate as (a) a standalone loose image file
    # (`image_candidates` below) or (b) a page inside a vector PDF
    # (`_render_vector_pdf_figures`) -- the two branches this method
    # handles. Embedded-raster-inside-a-PDF/DOCX extraction is deferred
    # (design.md "Approved LEAN scope"); no third arrival mode reaches this
    # method today, so no fixture/branch for it is added here.







