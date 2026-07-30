# src/docs/domain/source_conflict.py
from __future__ import annotations

import re
from dataclasses import dataclass

# Item K (design.md ADR-K): a curated table of mutually-exclusive term
# groups -- same vocabulary spirit as rules.py's DEFAULT_CONTESTED_STACK_TERMS,
# extended into FAMILIES where asserting one member genuinely excludes the
# others (a project can't real-world be both PHP/Laravel and bun.js/Node on
# the same backend). Deterministic, explainable, no NLP/embeddings (bound
# decision 1) -- false positives are cheap because the result is a WARN the
# agent adjudicates, never a block. ponytail: a small starter table, not an
# exhaustive taxonomy -- extend the groups here if a real drop surfaces a new
# contested pair, same escape hatch `DEFAULT_CONTESTED_STACK_TERMS` already
# uses.
_EXCLUSIVE_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "backend_runtime": {
        "php": ("php", "laravel"),
        "node": ("bun.js", "bun", "node.js", "nodejs", "express"),
        "python": ("django", "flask", "fastapi"),
    },
    "database": {
        "mysql": ("mysql",),
        "postgresql": ("postgresql", "postgres"),
        "mongodb": ("mongodb", "mongo"),
    },
    "hosting": {
        "firebase": ("firebase",),
        "supabase": ("supabase",),
        "gcp": ("gcp", "google cloud"),
        "aws": ("aws", "amazon web services"),
    },
}


@dataclass(frozen=True)
class Conflict:
    group: str
    members: tuple[str, ...]
    sources: tuple[str, ...]


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w]){re.escape(term.lower())}(?![\w])")


def _members_asserted(text: str) -> dict[str, set[str]]:
    lowered = text.lower()
    hits: dict[str, set[str]] = {}
    for group, members in _EXCLUSIVE_GROUPS.items():
        asserted = {
            member
            for member, terms in members.items()
            if any(_term_pattern(term).search(lowered) for term in terms)
        }
        if asserted:
            hits[group] = asserted
    return hits


def detect_conflicts(sources: list[tuple[str, str]]) -> list[Conflict]:
    """Pure, deterministic cross-source conflict check (item K): flags a
    curated exclusive term-group where at least two DIFFERENT ingested
    sources each assert a different member (e.g. one source says
    `Laravel`/PHP, another says `bun.js` -- the same project can't genuinely
    be both). A single source asserting multiple members of a group is
    within-document ambiguity, not a cross-source conflict, and is not
    flagged here (mirrors `review_cross_consistency`'s document-scoped
    checks, which stay the tool for that). Sorted output -- order-
    independent of `sources`' input order."""
    by_group: dict[str, dict[str, set[str]]] = {}
    for relative_path, text in sources:
        for group, members in _members_asserted(text).items():
            for member in members:
                by_group.setdefault(group, {}).setdefault(member, set()).add(relative_path)

    conflicts: list[Conflict] = []
    for group, member_sources in sorted(by_group.items()):
        all_sources = sorted({s for paths in member_sources.values() for s in paths})
        if len(member_sources) < 2 or len(all_sources) < 2:
            continue
        conflicts.append(
            Conflict(
                group=group,
                members=tuple(sorted(member_sources)),
                sources=tuple(all_sources),
            )
        )
    return conflicts
