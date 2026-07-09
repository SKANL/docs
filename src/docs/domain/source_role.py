# src/docs/domain/source_role.py
from __future__ import annotations

import re

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
_NORMATIVE_LEXICON = frozenset({"normativa", "norma", "reglas", "rules", "manual", "lineamientos"})
_EXAMPLE_LEXICON = frozenset(
    {
        "ejemplo", "ejemplos", "muestra", "sample", "reference", "referencia", "plantilla",
        "example", "examples",
    }
)
_EVIDENCE_LEXICON = frozenset(
    {
        "evidencia", "evidence", "anexo", "anexos", "sources", "fuentes", "capturas", "extracted",
    }
)

_ROLE_LEXICONS: dict[str, frozenset[str]] = {
    "normative": _NORMATIVE_LEXICON,
    "example": _EXAMPLE_LEXICON,
    "evidence": _EVIDENCE_LEXICON,
}

# NO content probes in this cut (design.md Decision 4, explicit "first cut"
# scope) -- kept deterministic and cheap; content probing is a documented
# future extension, not this change.

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(component: str) -> set[str]:
    return set(_WORD_RE.findall(component.casefold()))


def classify(relative_path: str) -> tuple[str, str, list[str]]:
    """Pure function: `relative_path` in, `(role, confidence, signals)` out
    -- zero AI judgment, zero I/O, zero randomness (spec: document-ingest
    "Source-Role Classification"). `role` is one of `normative`/`example`/
    `evidence`/`unknown`; `confidence` is `high`/`medium`/`low`.

    Folder-name lexicon match (any path component EXCEPT the filename
    itself) is the PRIMARY signal; a filename-stem match is SECONDARY,
    lower weight (design.md's own explanation: "folder intent is the
    deterministic signal that actually carries role"). A path with NO
    signal, or with EQUALLY-weighted conflicting signals for two different
    roles, is genuinely ambiguous -> `unknown`/`low` -- never an arbitrary
    pick (spec: "Ambiguous source is queued, not defaulted")."""
    parts = relative_path.split("/")
    folder_components = parts[:-1]
    filename = parts[-1] if parts else ""
    filename_stem = filename.rsplit(".", 1)[0] if "." in filename else filename

    folder_words: set[str] = set()
    for component in folder_components:
        folder_words |= _words(component)
    name_words = _words(filename_stem)

    scores: dict[str, float] = {}
    signals_by_role: dict[str, list[str]] = {}
    for role, lexicon in _ROLE_LEXICONS.items():
        folder_hits = sorted(folder_words & lexicon)
        name_hits = sorted(name_words & lexicon)
        if not folder_hits and not name_hits:
            continue
        # `min(1.0, 0.5*folder_hit + 0.3*name_hit)` style (design.md
        # Decision 4) -- a pure function of signal COUNTS, no floats
        # persisted beyond this computation.
        score = min(1.0, 0.5 * len(folder_hits) + 0.3 * len(name_hits))
        scores[role] = score
        signals_by_role[role] = [f"folder:{term}" for term in folder_hits] + [
            f"filename:{term}" for term in name_hits
        ]

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
