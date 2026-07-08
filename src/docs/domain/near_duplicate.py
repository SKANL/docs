# src/docs/domain/near_duplicate.py
from __future__ import annotations

from dataclasses import dataclass

from docs.domain.markdown_text import clean_markdown_text

# Fixed threshold (design.md Decision 5) -- deterministic, no seeded
# permutations (simhash/MinHash rejected for the first cut): exact Jaccard
# over 5-word shingles is cheap and needs zero randomness at this corpus
# size.
_SHINGLE_SIZE = 5
_JACCARD_THRESHOLD = 0.85

# Fidelity ranking (kept-vs-superseded), derived from the source `kind`
# recorded at ingest (design.md Decision 5). Lower rank = higher fidelity =
# preferred. `md` sources dropped directly into the inbox are treated as
# already-curated (no conversion loss). An unrecognized `kind` is treated
# as the LOWEST fidelity (safe default -- never silently preferred).
_FIDELITY_RANK: dict[str, int] = {
    "md": 0,  # curated_md
    "docx": 1,  # docx_converted_md
    "odt": 1,  # docx_converted_md (same pandoc conversion path)
    "pdf": 2,  # pdf_extracted_md
    "txt": 3,  # txt_md
}
_LOWEST_FIDELITY_RANK = max(_FIDELITY_RANK.values()) + 1


@dataclass(frozen=True)
class SourceDoc:
    relative_path: str
    kind: str
    text: str


@dataclass(frozen=True)
class DuplicateDecision:
    kept: str
    superseded: str
    jaccard: float
    reason: str


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    # Normalize: strip markdown markup (reuse markdown_text.clean_markdown_text
    # per design.md Decision 5), lowercase, collapse whitespace, then build
    # the set of overlapping SHINGLE_SIZE-word shingles. Pure set math.
    normalized = clean_markdown_text(text).lower()
    words = normalized.split()
    if len(words) < _SHINGLE_SIZE:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(
        tuple(words[i : i + _SHINGLE_SIZE]) for i in range(len(words) - _SHINGLE_SIZE + 1)
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fidelity_rank(kind: str) -> int:
    return _FIDELITY_RANK.get(kind, _LOWEST_FIDELITY_RANK)


def _rank_pair(a: SourceDoc, b: SourceDoc) -> tuple[SourceDoc, SourceDoc]:
    """Returns (kept, superseded). Higher fidelity wins; ties broken by
    POSIX `relative_path` (stable, design.md Decision 5)."""
    rank_a, rank_b = _fidelity_rank(a.kind), _fidelity_rank(b.kind)
    if rank_a != rank_b:
        return (a, b) if rank_a < rank_b else (b, a)
    return (a, b) if a.relative_path <= b.relative_path else (b, a)


def find_duplicates(docs: list[SourceDoc]) -> list[DuplicateDecision]:
    """Pairwise near-duplicate detection over `docs` (spec: document-ingest
    "Near-Duplicate Detection"). Deterministic, order-independent: the same
    set of `docs` in any input order produces the same decisions. A source
    already `superseded` by a higher-fidelity match is not compared again
    against further candidates (transitive near-duplicate CHAINS collapse
    onto the single highest-fidelity member, never a partial/ambiguous
    ordering)."""
    sorted_docs = sorted(docs, key=lambda d: d.relative_path)
    shingle_sets = {doc.relative_path: _shingles(doc.text) for doc in sorted_docs}

    decisions: list[DuplicateDecision] = []
    superseded_paths: set[str] = set()
    for i, doc_a in enumerate(sorted_docs):
        if doc_a.relative_path in superseded_paths:
            continue
        for doc_b in sorted_docs[i + 1 :]:
            if doc_b.relative_path in superseded_paths:
                continue
            score = _jaccard(shingle_sets[doc_a.relative_path], shingle_sets[doc_b.relative_path])
            if score < _JACCARD_THRESHOLD:
                continue
            kept, superseded = _rank_pair(doc_a, doc_b)
            decisions.append(
                DuplicateDecision(
                    kept=kept.relative_path,
                    superseded=superseded.relative_path,
                    jaccard=round(score, 4),
                    reason=f"near-duplicate content (jaccard={round(score, 4)})",
                )
            )
            superseded_paths.add(superseded.relative_path)
    return sorted(decisions, key=lambda d: (d.kept, d.superseded))
