# src/docs/domain/source_role.py
from __future__ import annotations

import re
import unicodedata

from docs.domain.ports.content_probe_port import ContentSignals

# Deterministic folder-name lexicon (design.md Decision 4) -- case-folded,
# matched as a WHOLE WORD within any relative-path component (so
# "guides/manual-estadia-tic/" hits "manual" even though the component
# itself is not an exact lexicon match). Primary signal.
#
# Extended (fresh-context verify, PR4 fix batch, WARNING-1 + SUGGESTION-1):
# design.md's original lists never included the English "example"/
# "examples", "extracted", or the singular "anexo" -- reproduced as a real,
# evidence-backed gap against THIS repo's OWN fixture folder names
# (example_tesina/, extracted/, from reporte-estadia-tic.json and PR3's own
# realistic-drop acceptance test): files in those real folders got ZERO
# folder-level signal and fell back to unconfirmed/unknown despite the
# folder name clearly signaling intent to a human. "extracted" maps to
# EVIDENCE (extracted/traceability content is plausibly always evidence
# material by construction, per the verify report's own recommendation).
# Public: reused by domain/doctor.py's manual auto-detect (item E) -- same
# vocabulary, never a second copy.
# "guia" (PR4, item D): unaccented ASCII form -- content text keeps its
# accent ("guía"), matched via `_content_words`' accent-folding below; path
# components are ASCII already so the folder/filename lexicon never needed
# accent-folding.
NORMATIVE_LEXICON = frozenset(
    {"normativa", "norma", "reglas", "rules", "manual", "lineamientos", "guia"}
)
_EXAMPLE_LEXICON = frozenset(
    {
        "ejemplo", "ejemplos", "muestra", "sample", "reference", "referencia", "plantilla",
        "example", "examples",
    }
)
_EVIDENCE_LEXICON = frozenset(
    {
        "evidencia", "evidence", "anexo", "anexos", "sources", "fuentes", "capturas", "extracted",
        "ficha", "empresa",
    }
)

_ROLE_LEXICONS: dict[str, frozenset[str]] = {
    "normative": NORMATIVE_LEXICON,
    "example": _EXAMPLE_LEXICON,
    "evidence": _EVIDENCE_LEXICON,
}

# Content-signal weight (design.md ADR-D, item D, PR4): "a lower weight
# than a folder hit [0.5], higher than a filename-stem hit [0.3]" -- an
# already-probed `ContentSignals` (adapter I/O, never read here) is scored
# by the SAME lexicons, so an arbitrarily-named file can still classify
# correctly by content alone.
_CONTENT_WEIGHT = 0.4

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(component: str) -> set[str]:
    return set(_WORD_RE.findall(component.casefold()))


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _content_words(signals: ContentSignals | None) -> set[str]:
    # Content text (PDF titles/headings, prose keywords) carries accents a
    # plain path component never does -- fold them so "GUÍA" matches
    # "guia" in the lexicon. Zero I/O: `signals` is already-probed strings.
    if signals is None:
        return set()
    texts = [signals.pdf_title, *signals.first_headings, *signals.head_keywords]
    words: set[str] = set()
    for text in texts:
        words |= set(_WORD_RE.findall(_strip_accents(text).casefold()))
    return words


def classify(
    relative_path: str, signals: ContentSignals | None = None
) -> tuple[str, str, list[str]]:
    """Pure function: `relative_path` (+ optional pre-probed `signals`) in,
    `(role, confidence, signals)` out -- zero AI judgment, zero I/O, zero
    randomness (spec: document-ingest "Source-Role Classification"). `role`
    is one of `normative`/`example`/`evidence`/`unknown`; `confidence` is
    `high`/`medium`/`low`. `signals=None` (the default) reproduces the
    original folder/filename-only behavior byte-for-byte (task 4.1
    regression guard) -- every existing caller is unaffected.

    Folder-name lexicon match (any path component EXCEPT the filename
    itself) is the PRIMARY signal; a filename-stem match is SECONDARY,
    lower weight; an optional content signal (item D, PR4 -- already
    probed by an adapter, e.g. PDF title/headings/keyword scan) is a THIRD,
    weaker-than-folder-stronger-than-filename signal (design.md's own
    explanation: "folder intent is the deterministic signal that actually
    carries role"). A path with NO signal, or with EQUALLY-weighted
    conflicting signals for two different roles, is genuinely ambiguous ->
    `unknown`/`low` -- never an arbitrary pick (spec: "Ambiguous source is
    queued, not defaulted")."""
    parts = relative_path.split("/")
    folder_components = parts[:-1]
    filename = parts[-1] if parts else ""
    filename_stem = filename.rsplit(".", 1)[0] if "." in filename else filename

    folder_words: set[str] = set()
    for component in folder_components:
        folder_words |= _words(component)
    name_words = _words(filename_stem)
    content_words = _content_words(signals)

    scores: dict[str, float] = {}
    signals_by_role: dict[str, list[str]] = {}
    for role, lexicon in _ROLE_LEXICONS.items():
        folder_hits = sorted(folder_words & lexicon)
        name_hits = sorted(name_words & lexicon)
        content_hits = sorted(content_words & lexicon)
        if not folder_hits and not name_hits and not content_hits:
            continue
        # `min(1.0, 0.5*folder_hit + 0.3*name_hit + 0.4*content_hit)`
        # style (design.md Decision 4 / ADR-D) -- a pure function of signal
        # COUNTS, no floats persisted beyond this computation.
        score = min(
            1.0,
            0.5 * len(folder_hits) + 0.3 * len(name_hits) + _CONTENT_WEIGHT * len(content_hits),
        )
        scores[role] = score
        signals_by_role[role] = (
            [f"folder:{term}" for term in folder_hits]
            + [f"filename:{term}" for term in name_hits]
            + [f"content:{term}" for term in content_hits]
        )

    if not scores:
        return "unknown", "low", []

    best_score = max(scores.values())
    best_roles = sorted(role for role, score in scores.items() if score == best_score)
    if len(best_roles) > 1:
        # Conflicting, EQUALLY-weighted signals across roles -- genuinely
        # ambiguous, never silently pick one (spec: "Ambiguous source is
        # queued, not defaulted").
        return "unknown", "low", []

    role = best_roles[0]
    confidence = "high" if best_score >= 0.5 else "medium"
    return role, confidence, signals_by_role[role]
