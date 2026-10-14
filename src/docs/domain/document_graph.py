"""Pure projection of a document's traceability data into a `SemanticGraph`.

A `DocumentSnapshot` holds primitives already read from disk by an adapter
(sections, manifests, provenance runs, revision entries); nothing here does IO.
Node ids are `<doc>/<kind>/<key>` with content- or path-derived keys, so the
same files always yield a byte-identical graph.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from docs.domain.apa import (
    citation_author_key,
    extract_apa_citations,
    extract_reference_entries,
    extract_references_block,
    reference_author_key,
)
from docs.domain.identity import sha256_bytes, sha256_content
from docs.domain.markdown_text import clean_markdown_text
from docs.domain.rules import requirement_present
from docs.domain.semantic_graph import GraphConfidence, SemanticEdge, SemanticGraph, SemanticNode

_INFERRED = GraphConfidence("inferred", 0.8)


@dataclass(frozen=True)
class SectionSnapshot:
    id: str
    title: str
    order: int
    body: str
    written: bool = True
    frontmatter: Mapping[str, Any] | None = None
    requirements: tuple[str, ...] = ()
    detect: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class FileEntry:
    path: str
    type: str = ""
    classification: str = ""
    sha256: str = ""


@dataclass(frozen=True)
class FactSnapshot:
    id: str
    classification: str
    claim: str
    source: str = ""
    source_path: str = ""


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    inputs: tuple[FileEntry, ...] = ()
    outputs: tuple[FileEntry, ...] = ()


@dataclass(frozen=True)
class RevisionSnapshot:
    id: str
    target_id: str
    request: str = ""
    ts: str = ""
    ripple: tuple[str, ...] = ()
    issues: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class DocumentSnapshot:
    doc_id: str
    title: str = ""
    sections: tuple[SectionSnapshot, ...] = ()
    sources: tuple[FileEntry, ...] = ()
    evidence: tuple[FileEntry, ...] = ()
    facts: tuple[FactSnapshot, ...] = ()
    runs: tuple[RunSnapshot, ...] = ()
    revisions: tuple[RevisionSnapshot, ...] = ()


def _short(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))[:12]


def _scalars(values: Mapping[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (values or {}).items() if isinstance(v, (str, int, float, bool))}


class _Builder:
    def __init__(self, doc_id: str) -> None:
        self.doc = doc_id
        self.nodes: dict[str, SemanticNode] = {}
        self.edges: dict[tuple[str, str, str], SemanticEdge] = {}

    def nid(self, kind: str, key: str) -> str:
        return f"{self.doc}/{kind}/{key}"

    def node(self, kind: str, key: str, label: str, **attributes: Any) -> str:
        node_id = self.nid(kind, key)
        if node_id not in self.nodes:
            self.nodes[node_id] = SemanticNode(
                node_id, kind, label or key, {"document": self.doc, **attributes}
            )
            if kind != "document":
                self.edge(self.nid("document", self.doc), node_id, "contains")
        return node_id

    def edge(self, source: str, target: str, relation: str, confidence: GraphConfidence | None = None) -> None:
        self.edges.setdefault(
            (source, target, relation),
            SemanticEdge(source, target, relation, confidence=confidence or GraphConfidence()),
        )


def _project(snap: DocumentSnapshot, out: _Builder) -> None:
    out.node("document", snap.doc_id, snap.title or snap.doc_id)
    _sections(snap, out)
    _evidence_and_claims(snap, out)
    _runs(snap, out)
    _revisions(snap, out)


def _sections(snap: DocumentSnapshot, out: _Builder) -> None:
    citations: dict[str, set[str]] = {}
    reference_ids: dict[str, list[str]] = {}
    for section in snap.sections:
        section_id = out.node(
            "section", section.id, section.title or section.id,
            order=section.order, written=section.written, **_scalars(section.frontmatter),
        )
        plain = clean_markdown_text(section.body).lower()
        detect = section.detect or {}
        for requirement in section.requirements:
            req_id = out.node("requirement", f"{section.id}/{_short(requirement)}", requirement, section=section.id)
            if requirement_present(requirement, plain, detect):
                out.edge(section_id, req_id, "satisfies", _INFERRED)
        prose = section.body[: len(section.body) - len(extract_references_block(section.body))]
        citations[section_id] = {citation_author_key(c) for c in extract_apa_citations(prose)}
        for entry in extract_reference_entries(section.body):
            ref_id = out.node("reference", _short(entry), entry, section=section.id)
            reference_ids.setdefault(reference_author_key(entry), []).append(ref_id)
    for section_id, keys in citations.items():
        for key in keys:
            for ref_id in reference_ids.get(key, ()):
                out.edge(section_id, ref_id, "references", _INFERRED)


def _evidence_and_claims(snap: DocumentSnapshot, out: _Builder) -> None:
    for source in snap.sources:
        out.node("source", source.path, source.path, type=source.type, sha256=source.sha256)
    evidence_ids: dict[str, str] = {}
    for item in snap.evidence:
        evidence_ids[item.path] = out.node(
            "evidence", item.path, item.path,
            type=item.type, classification=item.classification, sha256=item.sha256,
        )
    for fact in snap.facts:
        claim_id = out.node(
            "claim", fact.id, fact.claim, classification=fact.classification, source=fact.source
        )
        if fact.source_path in evidence_ids:
            out.edge(evidence_ids[fact.source_path], claim_id, "supports")


def _runs(snap: DocumentSnapshot, out: _Builder) -> None:
    for run in sorted(snap.runs, key=lambda r: r.run_id):
        inputs = [out.node("input", i.path, i.path, sha256=i.sha256) for i in run.inputs]
        for artifact in run.outputs:
            artifact_id = out.node("artifact", artifact.path, artifact.path, sha256=artifact.sha256, run_id=run.run_id)
            for input_id in inputs:
                out.edge(artifact_id, input_id, "derived_from")


def _revisions(snap: DocumentSnapshot, out: _Builder) -> None:
    for revision in snap.revisions:
        rev_id = out.node(
            "revision", revision.id, revision.request or revision.id,
            target=revision.target_id, ts=revision.ts,
        )
        for target in (revision.target_id, *revision.ripple):
            section_id = out.nid("section", target)
            if section_id in out.nodes:
                out.edge(rev_id, section_id, "revises")
        for issue in revision.issues:
            finding_id = out.node(
                "finding", _short(sha256_content(dict(issue))), str(issue.get("message", "")),
                severity=str(issue.get("severity", "")), code=str(issue.get("code", "")),
            )
            out.edge(rev_id, finding_id, "affects")


def project_document_graph(snapshots: Iterable[DocumentSnapshot]) -> SemanticGraph:
    nodes: dict[str, SemanticNode] = {}
    edges: dict[tuple[str, str, str], SemanticEdge] = {}
    for snap in snapshots:
        builder = _Builder(snap.doc_id)
        _project(snap, builder)
        nodes.update(builder.nodes)
        edges.update(builder.edges)
    return SemanticGraph(tuple(nodes.values()), tuple(edges.values()))
