"""Read a workspace's documents from disk and project them into a `SemanticGraph`.

The projection itself is pure (`domain/document_graph.py`); this adapter only
gathers primitives. The result is cached per workspace root and invalidated
by the (path, mtime) signature of every file it reads, so an unchanged
workspace costs a handful of `stat` calls per query.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from docs.domain.collection import dedupe_facts, identify_facts
from docs.domain.document_graph import (
    DocumentSnapshot,
    FactSnapshot,
    FileEntry,
    RevisionSnapshot,
    RunSnapshot,
    SectionSnapshot,
    project_document_graph,
)
from docs.domain.identity import read_json_object, sha256_bytes, sha256_content
from docs.domain.markdown_text import split_frontmatter
from docs.domain.models.template import Template
from docs.domain.paths import is_within
from docs.domain.semantic_graph import SemanticGraph

_MANIFESTS = ("source-manifest.json", "code-evidence-manifest.json", "issues-manifest.json")


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class DocumentGraphReader:
    """`get()` returns the projected graph of every document under one workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._signature: tuple[tuple[str, int], ...] | None = None
        self._graph = SemanticGraph()
        self._digests: dict[tuple[str, int, int], str] = {}

    def get(self) -> SemanticGraph:
        signature = self._read_signature()
        if signature != self._signature:
            self._graph = project_document_graph(self._snapshot(doc) for doc in self._document_dirs())
            self._signature = signature
        return self._graph

    def _document_dirs(self) -> list[Path]:
        return sorted(p.parent for p in (self.root / "documents").glob("*/document.json"))

    def _watched_files(self) -> list[Path]:
        files = sorted((self.root / "templates").glob("*.json"))
        for doc in self._document_dirs():
            sections = doc / "sections"
            files += [doc / "document.json", doc / "inbox" / "_source-manifest.json", doc / "runs" / "provenance.json"]
            files += [sections / name for name in _MANIFESTS]
            files += [sections / "_revisions" / "revision-log.json"]
            files += sorted(sections.glob("*.md"))
            files += [p for _, p in self._ledger_inputs(doc) if p is not None]
        return files

    # -- paths -------------------------------------------------------------

    def _locate(self, doc: Path, raw: str, base: Path) -> tuple[str, Path | None]:
        """Stable key for a stored path, and the real file when it lives inside this workspace.

        The ledger stores a path relative to `runs/` or absolute; manifests store
        absolute paths. Both become relative to the document, so the same file
        has one node key whatever form recorded it. A path that resolves outside
        the workspace keeps its raw form and is never opened.
        """
        candidate = Path(raw)
        resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
        if not is_within(resolved, self.root):
            return raw, None
        return Path(os.path.relpath(resolved, doc.resolve())).as_posix(), resolved

    def _ledger_inputs(self, doc: Path) -> list[tuple[str, Path | None]]:
        runs = (read_json_object(doc / "runs" / "provenance.json") or {}).get("runs")
        paths = {
            str(path)
            for record in (runs.values() if isinstance(runs, dict) else ())
            if isinstance(record, dict) and isinstance(record.get("inputs"), dict)
            for path in record["inputs"]
        }
        return [self._locate(doc, raw, doc / "runs") for raw in sorted(paths)]

    def _digest(self, path: Path | None) -> str:
        """sha256 of a file now; "" when it is gone or not readable. Cached per (path, mtime, size)."""
        try:
            if path is None:
                return ""
            info = path.stat()
            key = (str(path), info.st_mtime_ns, info.st_size)
            if key not in self._digests:
                self._digests[key] = sha256_bytes(path.read_bytes())
            return self._digests[key]
        except OSError:
            return ""

    def _entries(self, doc: Path, value: Any) -> tuple[FileEntry, ...]:
        return tuple(
            FileEntry(
                self._locate(doc, str(item["path"]), doc)[0], str(item.get("type", "")),
                str(item.get("classification", "")), str(item.get("sha256", "")),
            )
            for item in _dicts(value)
            if item.get("path")
        )

    def _read_signature(self) -> tuple[tuple[str, int], ...]:
        # ponytail: (path, mtime_ns) of every file read, not just the max mtime:
        # a deleted or renamed file lowers no mtime but must still invalidate.
        signature = []
        for path in self._watched_files():
            try:
                signature.append((str(path), path.stat().st_mtime_ns))
            except OSError:
                continue
        return tuple(signature)

    # -- one document ------------------------------------------------------

    def _snapshot(self, doc: Path) -> DocumentSnapshot:
        document = read_json_object(doc / "document.json") or {}
        manifests = [read_json_object(doc / "sections" / name) or {} for name in _MANIFESTS]
        evidence_items = _dicts(manifests[0].get("sources")) + _dicts(manifests[1].get("files"))
        evidence = self._entries(doc, evidence_items)
        template = self._template(str(document.get("template", "")))
        # the fact ledger users read starts with the template's seed facts
        seeds = [
            {"classification": "confirmado", **item, "source": "template"}
            for item in _dicts((template.model_extra or {}).get("ledger_seed") if template else None)
            if item.get("claim")
        ]
        raw_facts = [
            *seeds,
            *_dicts(manifests[0].get("facts")),
            *_dicts(manifests[1].get("facts")),
            *({**item, "claim": item.get("claim") or item.get("title", "")} for item in _dicts(manifests[2].get("issues"))),
        ]
        facts = identify_facts(
            dedupe_facts([f for f in raw_facts if f.get("claim")]), {str(e["path"]) for e in evidence_items if "path" in e}
        )
        inbox = read_json_object(doc / "inbox" / "_source-manifest.json") or {}
        return DocumentSnapshot(
            doc_id=doc.name,
            title=str(document.get("title", doc.name)),
            sections=self._sections(doc, template),
            sources=tuple(
                FileEntry(
                    self._locate(doc, f"inbox/{s['relative_path']}", doc)[0],
                    str(s.get("confirmed_role") or s.get("proposed_role") or ""),
                )
                for s in _dicts(inbox.get("sources"))
                if s.get("relative_path")
            ),
            evidence=evidence,
            facts=tuple(
                FactSnapshot(
                    f["id"], str(f.get("classification", "pendiente")), str(f["claim"]),
                    str(f.get("source", "")),
                    self._locate(doc, str(f["source_path"]), doc)[0] if f.get("source_path") else "",
                )
                for f in facts
            ),
            runs=self._runs(doc),
            revisions=self._revisions(doc),
        )

    def _sections(self, doc: Path, template: Template | None) -> tuple[SectionSnapshot, ...]:
        sections_dir = doc / "sections"
        found: list[tuple[int, str, str, Any, Path]] = []
        if template is None:
            # ponytail: no template -> sections are whatever files exist, without
            # requirements. Upgrade path: surface "template missing" as a finding.
            for path in sorted(sections_dir.glob("[0-9][0-9][0-9]-*.md")):
                number, _, section_id = path.stem.partition("-")
                found.append((int(number), section_id, section_id, None, path))
        else:
            for s in template.sections:
                path = sections_dir / f"{s.order:03d}-{s.id}.md"
                found.append((s.order, s.id, s.title, template.section_contracts.get(s.id), path))
        snapshots = []
        for order, section_id, title, contract, path in found:
            try:
                frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
                written = True
            except OSError:
                frontmatter, body, written = {}, "", False
            snapshots.append(
                SectionSnapshot(
                    section_id, title, order, body, written, frontmatter,
                    tuple(contract.required_content) if contract else (),
                    dict(contract.detect) if contract else None,
                )
            )
        return tuple(snapshots)

    def _template(self, name: str) -> Template | None:
        if not name:
            return None
        try:
            return Template.from_json((self.root / "templates" / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _runs(self, doc: Path) -> tuple[RunSnapshot, ...]:
        runs = (read_json_object(doc / "runs" / "provenance.json") or {}).get("runs")
        return tuple(
            RunSnapshot(
                str(run_id),
                tuple(self._ledger_entry(doc, record.get("inputs"), measure=True)),
                tuple(self._ledger_entry(doc, record.get("outputs"), measure=False)),
            )
            for run_id, record in sorted((runs if isinstance(runs, dict) else {}).items())
            if isinstance(record, dict)
        )

    def _ledger_entry(self, doc: Path, hashes: Any, *, measure: bool) -> list[FileEntry]:
        located = ((self._locate(doc, str(raw), doc / "runs"), str(digest)) for raw, digest in sorted((hashes if isinstance(hashes, dict) else {}).items()))
        return [
            FileEntry(key, sha256=digest, current_sha256=self._digest(path) if measure else None)
            for (key, path), digest in located
        ]

    @staticmethod
    def _revisions(doc: Path) -> tuple[RevisionSnapshot, ...]:
        log = read_json_object(doc / "sections" / "_revisions" / "revision-log.json") or {}
        return tuple(
            RevisionSnapshot(
                # legacy entries predate the persisted id: derive the same content hash
                str(entry.get("id") or sha256_content(entry)),
                str(entry.get("section_id", "")),
                str(entry.get("request", "")),
                str(entry.get("ts", "")),
                tuple(str(s) for s in entry.get("ripple", [])),
                tuple(_dicts(entry.get("issues"))),
            )
            for entry in _dicts(log.get("entries"))
        )
