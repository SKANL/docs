# src/docs/domain/near_duplicate.py
from __future__ import annotations

from dataclasses import dataclass

from docs.domain.markdown_text import (
    _ACCENT_TRANSLATION,
    clean_markdown_text,
    strip_frontmatter_and_markdown,
)

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


def _normalize_for_shingling(text: str) -> str:
    # Normalization pipeline (design.md Decision 5), REUSING existing
    # markdown_text utilities rather than duplicating their logic:
    # 1. `strip_frontmatter_and_markdown` removes frontmatter, code fences,
    #    images/links, and structural markup (headings `#`, lists `-`,
    #    blockquotes `>`, tables `|`) -- fixed here (WARNING-2, fresh-context
    #    verify, PR4 fix batch): `clean_markdown_text` alone strips only
    #    bold/italic/inline-code markers, leaving structural chars as
    #    spurious "words" that can drag a genuinely similar,
    #    heavily-formatted document below the similarity threshold.
    # 2. `clean_markdown_text` strips any remaining bold/italic/code
    #    markers and collapses whitespace.
    # 3. `_ACCENT_TRANSLATION` folds accented Spanish vowels/eñe to their
    #    bare form -- fixed here (CRITICAL-1, fresh-context verify, PR4 fix
    #    batch): an OCR/PDF-extraction pipeline commonly diverges from a
    #    hand-curated original by accent handling alone, and Spanish prose
    #    is accent-dense enough that this alone previously made virtually
    #    every shingle differ (observed jaccard ~0.12 for otherwise-identical
    #    content), silently missing this feature's own flagship real-world
    #    scenario (design.md Decision 5's cited exemplar).
    text = strip_frontmatter_and_markdown(text)
    text = clean_markdown_text(text)
    return text.translate(_ACCENT_TRANSLATION).lower()


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    # Build the set of overlapping SHINGLE_SIZE-word shingles over
    # normalized text. Pure set math.
    #
    # WARNING-3 (fresh-context verify, PR4 fix batch), documented and
    # PINNED, not changed by this fix batch: a document with FEWER than
    # SHINGLE_SIZE words collapses to a single whole-text "shingle" (a
    # tuple of however many words there are) -- two such short documents
    # can only ever match EXACTLY (jaccard=1.0, identical tuple) or be
    # entirely DISJOINT (jaccard=0.0, different tuple); there is no
    # graduated "near" match possible below the shingle-size threshold.
    # Safe (never a FALSE duplicate flag) but zero fuzzy-matching value for
    # genuinely near-duplicate short files (e.g. a one-line section summary
    # edited slightly).
    normalized = _normalize_for_shingling(text)
    words = normalized.split()
    if len(words) < _SHINGLE_SIZE:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(
        tuple(words[i : i + _SHINGLE_SIZE]) for i in range(len(words) - _SHINGLE_SIZE + 1)
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    # SUGGESTION-2 (fresh-context verify, PR4 fix batch): an EMPTY document
    # (zero shingles -- no real content after normalization) is never
    # comparable to anything, including another empty document -- two
    # blank/failed conversions are not "100% similar", they simply have
    # nothing to compare. `find_duplicates` also filters empty documents
    # out of the pairwise pass entirely (defense in depth), but this
    # function stays safe on its own regardless of caller.
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
    ordering).

    O(n^2) pairwise comparison (SUGGESTION-3, fresh-context verify, PR4 fix
    batch) is a DELIBERATE, documented design choice, not an oversight --
    design.md's Decision 5 explicitly rejects simhash/MinHash for the first
    cut ("at this corpus size exact Jaccard over shingles is cheap and
    needs zero seeds"). No chunking/blocking/size-based short-circuit
    exists; a very large inbox drop (hundreds of files) would degrade
    silently rather than fail loudly. Revisit the algorithm, not just add a
    guard, if corpus size ever demands it."""
    # SUGGESTION-2 (fresh-context verify, PR4 fix batch): an EMPTY document
    # (no real content after normalization) is skipped from the pairwise
    # pass ENTIRELY, not merely scored 0.0 by `_jaccard` -- so two blank or
    # failed conversions are never candidates for a duplicate decision,
    # regardless of any future change to `_jaccard`'s own edge-case
    # handling.
    sorted_docs = sorted(docs, key=lambda d: d.relative_path)
    shingle_sets = {doc.relative_path: _shingles(doc.text) for doc in sorted_docs}
    comparable_docs = [doc for doc in sorted_docs if shingle_sets[doc.relative_path]]

    decisions: list[DuplicateDecision] = []
    superseded_paths: set[str] = set()
    for i, doc_a in enumerate(comparable_docs):
        if doc_a.relative_path in superseded_paths:
            continue
        for doc_b in comparable_docs[i + 1 :]:
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
