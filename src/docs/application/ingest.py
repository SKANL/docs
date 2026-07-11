# src/docs/application/ingest.py
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from docs.domain.figure_catalog import FigureEntry, build as build_figure_catalog
from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.near_duplicate import DuplicateDecision, SourceDoc, find_duplicates
from docs.domain.ports.image_metadata_port import ImageMetadataPort
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.ports.source_type_detector_port import SourceTypeDetectorPort
from docs.domain.source_role import classify

_DETECTION_REPORT_NAME = "_detection.json"
_SOURCE_MANIFEST_NAME = "_source-manifest.json"
_CLASSIFICATION_QUEUE_NAME = "_classification-queue.json"
_PLACEMENT_QUEUE_NAME = "_placement-queue.json"

# PR3 verify follow-up (finding a): these are the harness's OWN
# `_`-prefixed bookkeeping files, always written at `inbox_dir` root --
# a rescan finding them gets a distinct `"harness_artifact"` ignored-reason,
# never conflated with a genuine user `_`-prefixed file.
_HARNESS_ARTIFACT_NAMES = frozenset(
    {_DETECTION_REPORT_NAME, _SOURCE_MANIFEST_NAME, _CLASSIFICATION_QUEUE_NAME, _PLACEMENT_QUEUE_NAME}
)

# Verbatim-asset heuristic (design.md Decision 6a): an image anywhere
# outside `inbox/assets/`, or a `.docx` whose path signals cover/portada/
# anexo-visual intent, is PROPOSED (never auto-routed) to the placement
# queue. ponytail: substring match on the lowercased relative path, no
# content probing -- same grain as source_role.py's folder lexicon.
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"})
_COVER_KEYWORDS = ("portada", "cover")
_BACK_KEYWORDS = ("anexo-visual", "anexo_visual")

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


def _guess_asset_kind(relative_posix: str) -> str | None:
    lower = relative_posix.lower()
    if any(keyword in lower for keyword in _COVER_KEYWORDS):
        return "cover"
    if any(keyword in lower for keyword in _BACK_KEYWORDS):
        return "back"
    return None


def _is_heuristic_asset_candidate(relative_posix: str) -> bool:
    suffix = Path(relative_posix).suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        return True
    return suffix == ".docx" and _guess_asset_kind(relative_posix) is not None


def _structure_part_for_kind(kind: str, asset_name: str) -> dict[str, str]:
    part_type = "cover_from_asset" if kind == "cover" else "embed_docx"
    return {"type": part_type, "asset": asset_name}


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
        image_metadata: ImageMetadataPort | None = None,
    ) -> None:
        self.detector = detector
        self.handlers = dict(handlers)
        self.writer: IngestArtifactWriter = writer or _InlineJsonWriter()
        self.image_metadata = image_metadata

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
            placements = self._route_and_queue_assets(
                inbox_dir, declared_assets, heuristic_candidates, assets_dir
            )
            self._build_figure_catalog(inbox_dir, sections_dir, declared_assets, heuristic_candidates)

            # Front D (design.md Decision 4): classify every real source
            # entry, merge any externally-confirmed role from the PRIOR
            # classification queue (the interface where confirmation
            # enters), resolve the draft/strict gate, then (re)write the
            # queue. Front E (Decision 5): near-duplicate pass over the
            # just-produced `ingested/` outputs, preserving any manual
            # kept/superseded reversal already recorded in the manifest.
            manifest_sources = self._build_manifest_sources(inbox_dir, entries, strict)
            self._write_classification_queue(inbox_dir, manifest_sources)
            duplicates = self._find_near_duplicates(inbox_dir, manifest_sources)
            self._write_source_manifest(inbox_dir, manifest_sources, duplicates, placements)
        report = {
            "processed": sum(1 for e in entries if e.get("status") != "empty_dir"),
            "files": entries,
            "ignored": ignored,
            "media_cleanup": self._clean_orphan_media(sections_dir / "ingested"),
        }
        self._write_detection_report(inbox_dir, report)
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
            if rel in _HARNESS_ARTIFACT_NAMES:
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
        self.writer.write_json(inbox_dir / _DETECTION_REPORT_NAME, report)

    def _write_source_manifest(
        self,
        inbox_dir: Path,
        manifest_sources: list[dict[str, Any]],
        duplicates: list[dict[str, Any]],
        placements: list[dict[str, Any]],
    ) -> None:
        # `inbox/_source-manifest.json` (design.md's artifact map): distinct
        # from the collection stage's `sections/source-manifest.json`.
        # `_`-prefixed, so the recursive walk itself always skips it, same
        # as `_detection.json`.
        payload = {
            "schema": 1,
            "sources": manifest_sources,
            "duplicates": duplicates,
            "placements": placements,
        }
        self.writer.write_json(inbox_dir / _SOURCE_MANIFEST_NAME, payload)

    # --- Front D: source-role classification (design.md Decision 4) -----

    def _build_manifest_sources(
        self, inbox_dir: Path, entries: list[dict[str, Any]], strict: bool
    ) -> list[dict[str, Any]]:
        # Classification is a PURE function of relative_path -- zero AI
        # judgment, zero I/O, zero randomness at runtime (spec:
        # document-ingest "Source-Role Classification"). External
        # confirmation enters ONLY through the classification queue file
        # (an agent/human edits it); a prior confirmation round-trips
        # forward into this run's manifest AND the freshly-rewritten queue.
        prior_confirmed = self._read_prior_confirmed_roles(inbox_dir)
        sources: list[dict[str, Any]] = []
        for entry in entries:
            if entry.get("status") == "empty_dir":
                continue
            relative_path = entry["relative_path"]
            role, confidence, signals = classify(relative_path)
            confirmed_role = prior_confirmed.get(relative_path)
            manifest_entry = dict(entry)
            manifest_entry["proposed_role"] = role
            manifest_entry["confidence"] = confidence
            manifest_entry["signals"] = signals
            manifest_entry["confirmed_role"] = confirmed_role
            manifest_entry["role_status"] = self._resolve_role_gate(role, confirmed_role, strict)
            sources.append(manifest_entry)
        return sources

    def _resolve_role_gate(
        self, proposed_role: str, confirmed_role: str | None, strict: bool
    ) -> dict[str, Any]:
        # Gating (design.md Decision 4, spec: "Confirmed role recorded and
        # enforced"): a confirmed role always routes the source under that
        # role. Unconfirmed: draft admits with the proposed role and a
        # PENDIENTE-style gap entry; strict blocks outright (consistent
        # with the draft/strict split, Decision 7).
        if confirmed_role:
            return {"effective_role": confirmed_role, "blocked": False, "gap": None}
        if strict:
            return {
                "effective_role": None,
                "blocked": True,
                "gap": (
                    f"Rol sin confirmar (propuesto: {proposed_role}); "
                    "bloqueado en modo estricto hasta que se confirme."
                ),
            }
        return {
            "effective_role": proposed_role,
            "blocked": False,
            "gap": f"PENDIENTE: rol sin confirmar (propuesto: {proposed_role}).",
        }

    def _read_prior_confirmed_roles(self, inbox_dir: Path) -> dict[str, str]:
        queue_path = inbox_dir / _CLASSIFICATION_QUEUE_NAME
        if not queue_path.exists():
            return {}
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        confirmed: dict[str, str] = {}
        for relative_path, entry in data.get("entries", {}).items():
            role = entry.get("confirmed_role")
            if role:
                confirmed[relative_path] = role
        return confirmed

    def _write_classification_queue(
        self, inbox_dir: Path, manifest_sources: list[dict[str, Any]]
    ) -> None:
        # `inbox/_classification-queue.json` (design.md Decision 4): the
        # interface where EXTERNAL confirmation enters. Atomic, sort_keys
        # writer via IngestArtifactWriter (Decision 9); entries KEYED BY
        # relative_path.
        entries = {
            source["relative_path"]: {
                "proposed_role": source["proposed_role"],
                "confidence": source["confidence"],
                "signals": source["signals"],
                "confirmed_role": source.get("confirmed_role"),
            }
            for source in manifest_sources
        }
        payload = {"schema": 1, "entries": entries}
        self.writer.write_json(inbox_dir / _CLASSIFICATION_QUEUE_NAME, payload)

    # --- Front E: near-duplicate detection (design.md Decision 5) -------

    def _find_near_duplicates(
        self, inbox_dir: Path, manifest_sources: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # A post-ingest pass over the just-produced `ingested/` outputs
        # (spec: document-ingest "Near-Duplicate Detection") -- their
        # content is stable and already deterministic, so this sees final
        # normalized artifacts, not raw heterogeneous sources.
        docs: list[SourceDoc] = []
        for source in manifest_sources:
            output = source.get("output")
            if not output:
                continue
            try:
                text = Path(output).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            docs.append(SourceDoc(relative_path=source["relative_path"], kind=source["kind"], text=text))

        manual_overrides = self._read_manual_duplicate_overrides(inbox_dir)
        fresh_decisions = find_duplicates(docs)
        final_decisions: list[dict[str, Any]] = []
        for decision in fresh_decisions:
            pair_key = frozenset({decision.kept, decision.superseded})
            override = manual_overrides.get(pair_key)
            if override is not None:
                # Reversible (spec: "Duplicate decision is reversible") --
                # a human edited kept/superseded for this pair in the
                # manifest; respect that choice, but keep the FRESH jaccard
                # score/reason (reflects current content).
                final_decisions.append(
                    {
                        "kept": override.kept,
                        "superseded": override.superseded,
                        "jaccard": decision.jaccard,
                        "reason": decision.reason,
                    }
                )
            else:
                final_decisions.append(
                    {
                        "kept": decision.kept,
                        "superseded": decision.superseded,
                        "jaccard": decision.jaccard,
                        "reason": decision.reason,
                    }
                )
        return sorted(final_decisions, key=lambda d: (d["kept"], d["superseded"]))

    def _read_manual_duplicate_overrides(
        self, inbox_dir: Path
    ) -> dict[frozenset[str], DuplicateDecision]:
        manifest_path = inbox_dir / _SOURCE_MANIFEST_NAME
        if not manifest_path.exists():
            return {}
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        overrides: dict[frozenset[str], DuplicateDecision] = {}
        for entry in data.get("duplicates", []):
            kept, superseded = entry.get("kept"), entry.get("superseded")
            if not kept or not superseded:
                continue
            overrides[frozenset({kept, superseded})] = DuplicateDecision(
                kept=kept,
                superseded=superseded,
                jaccard=entry.get("jaccard", 0.0),
                reason=entry.get("reason", ""),
            )
        return overrides

    # --- Front F: verbatim assets + placement queue (design.md Decision 6a)

    def _route_and_queue_assets(
        self,
        inbox_dir: Path,
        declared_assets: list[tuple[Path, str]],
        heuristic_candidates: list[tuple[Path, str]],
        assets_dir: Path | None,
    ) -> list[dict[str, Any]]:
        # Pipeline order (design.md Decision 6a): asset-routing -> recursive
        # walk -> ingest -> near-dup -> classification queue. Declared
        # assets (inbox/assets/) are routed UNCONDITIONALLY -- their
        # presence there IS the declaration. Heuristic candidates elsewhere
        # (image files, or a cover/portada/anexo-visual-signaled .docx) are
        # only PROPOSED, never auto-routed -- and excluded from `sources` by
        # `_walk_inbox` so they are never flattened to markdown before a
        # human confirms a placement either way.
        prior_confirmed = self._read_prior_confirmed_placements(inbox_dir)
        candidates: dict[str, str] = {}  # relative_path -> proposed_kind ("" if none)
        for _path, rel in declared_assets:
            candidates[rel] = _guess_asset_kind(rel) or ""
        for _path, rel in heuristic_candidates:
            candidates[rel] = _guess_asset_kind(rel) or ""

        declared_by_rel = {rel: path for path, rel in declared_assets}
        source_by_rel = {rel: path for path, rel in heuristic_candidates}

        queue_entries: dict[str, dict[str, Any]] = {}
        placements: list[dict[str, Any]] = []
        for rel in sorted(candidates):
            proposed_kind = candidates[rel] or None
            confirmed_placement = prior_confirmed.get(rel)
            queue_entries[rel] = {
                "proposed_kind": proposed_kind,
                "confirmed_placement": confirmed_placement,
            }

            src_path = declared_by_rel.get(rel) or source_by_rel.get(rel)
            asset_name = Path(rel).name
            routed = rel in declared_by_rel  # unconditionally routed
            if confirmed_placement and assets_dir is not None and src_path is not None:
                # A CONFIRMED heuristic asset is routed now too (declared
                # ones were already routed below, copy is idempotent).
                self._copy_asset(src_path, assets_dir, asset_name)
                routed = True
            structure_part = (
                _structure_part_for_kind(confirmed_placement, asset_name)
                if confirmed_placement
                else None
            )
            placements.append(
                {
                    "relative_path": rel,
                    "proposed_kind": proposed_kind,
                    "confirmed_placement": confirmed_placement,
                    "routed": routed,
                    "structure_part": structure_part,
                }
            )

        if assets_dir is not None:
            for path, rel in declared_assets:
                self._copy_asset(path, assets_dir, Path(rel).name)

        self.writer.write_json(
            inbox_dir / _PLACEMENT_QUEUE_NAME, {"schema": 1, "entries": queue_entries}
        )
        return placements

    def _copy_asset(self, src: Path, assets_dir: Path, name: str) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, assets_dir / name)

    def _read_prior_confirmed_placements(self, inbox_dir: Path) -> dict[str, str]:
        queue_path = inbox_dir / _PLACEMENT_QUEUE_NAME
        if not queue_path.exists():
            return {}
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        confirmed: dict[str, str] = {}
        for relative_path, entry in data.get("entries", {}).items():
            placement = entry.get("confirmed_placement")
            if placement:
                confirmed[relative_path] = placement
        return confirmed

    # --- Front F: figure catalog (design.md Decision 6b) -----------------

    def _build_figure_catalog(
        self,
        inbox_dir: Path,
        sections_dir: Path,
        declared_assets: list[tuple[Path, str]],
        heuristic_candidates: list[tuple[Path, str]],
    ) -> None:
        image_candidates = [
            (path, rel)
            for path, rel in (*declared_assets, *heuristic_candidates)
            if Path(rel).suffix.lower() in _IMAGE_EXTENSIONS
        ]
        figures: list[FigureEntry] = []
        for path, rel in sorted(image_candidates, key=lambda item: item[1]):
            data = path.read_bytes()
            dimensions = self.image_metadata.read_dimensions(path) if self.image_metadata else None
            width, height = dimensions if dimensions is not None else (None, None)
            figures.append(
                FigureEntry(
                    sha256=sha256_hex(data),
                    width_px=width,
                    height_px=height,
                    origin_relative_path=rel,
                )
            )
        catalog_path = sections_dir / "figure-catalog.json"
        self.writer.write_json(catalog_path, build_figure_catalog(figures))
