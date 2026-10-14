"""Read a workspace's documents from disk and project them into a `SemanticGraph`.

The projection itself is pure (`domain/document_graph.py`); this adapter only
gathers primitives. The result is cached per workspace root and invalidated
by the (path, mtime) signature of every file it reads, so an unchanged
workspace costs a handful of `stat` calls per query.
"""

from __future__ import annotations

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
from docs.domain.identity import read_json_object, sha256_content
from docs.domain.markdown_text import split_frontmatter
from docs.domain.models.template import Template
from docs.domain.semantic_graph import SemanticGraph

_MANIFESTS = ("source-manifest.json", "code-evidence-manifest.json", "issues-manifest.json")


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _entries(value: Any) -> tuple[FileEntry, ...]:
    return tuple(
        FileEntry(
            str(item["path"]), str(item.get("type", "")), str(item.get("classification", "")), str(item.get("sha256", ""))
        )
        for item in _dicts(value)
        if item.get("path")
    )


def _hashed(value: Any) -> tuple[FileEntry, ...]:
    mapping = value if isinstance(value, dict) else {}
    return tuple(FileEntry(str(path), sha256=str(digest)) for path, digest in sorted(mapping.items()))


class DocumentGraphReader:
    """`get()` returns the projected graph of every document under one workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._signature: tuple[tuple[str, int], ...] | None = None
        self._graph = SemanticGraph()

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
        return files

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
        evidence = _entries(manifests[0].get("sources")) + _entries(manifests[1].get("files"))
        raw_facts = [
            *_dicts(manifests[0].get("facts")),
            *_dicts(manifests[1].get("facts")),
            *({**item, "claim": item.get("claim") or item.get("title", "")} for item in _dicts(manifests[2].get("issues"))),
        ]
        facts = identify_facts(dedupe_facts([f for f in raw_facts if f.get("claim")]), {e.path for e in evidence})
        inbox = read_json_object(doc / "inbox" / "_source-manifest.json") or {}
        return DocumentSnapshot(
            doc_id=doc.name,
            title=str(document.get("title", doc.name)),
            sections=self._sections(doc, str(document.get("template", ""))),
            sources=tuple(
                FileEntry(str(s["relative_path"]), str(s.get("confirmed_role") or s.get("proposed_role") or ""))
                for s in _dicts(inbox.get("sources"))
                if s.get("relative_path")
            ),
            evidence=evidence,
            facts=tuple(
                FactSnapshot(
                    f["id"], str(f.get("classification", "pendiente")), str(f["claim"]),
                    str(f.get("source", "")), str(f.get("source_path", "")),
                )
                for f in facts
            ),
            runs=self._runs(doc),
            revisions=self._revisions(doc),
        )

    def _sections(self, doc: Path, template_name: str) -> tuple[SectionSnapshot, ...]:
        sections_dir = doc / "sections"
        template = self._template(template_name)
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

    @staticmethod
    def _runs(doc: Path) -> tuple[RunSnapshot, ...]:
        runs = (read_json_object(doc / "runs" / "provenance.json") or {}).get("runs")
        return tuple(
            RunSnapshot(str(run_id), _hashed(record.get("inputs")), _hashed(record.get("outputs")))
            for run_id, record in sorted((runs if isinstance(runs, dict) else {}).items())
            if isinstance(record, dict)
        )

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
