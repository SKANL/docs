# tests/unit/domain/test_source_role.py
"""Source-role classification (Front D, design.md Decision 4; spec:
document-ingest "Source-Role Classification"). Deterministic folder-name
lexicon (primary) + filename-pattern (secondary, lower weight) signals --
NO content probes in this cut (design.md's explicit "first cut" scope).
`classify(relative_path)` is a pure function: zero AI judgment at runtime,
pure data in, pure data out."""
from __future__ import annotations

from docs.domain.source_role import classify


# --- 8.1: folder-lexicon signal (primary) --------------------------------


def test_folder_lexicon_normative_family_classifies_unambiguously():
    role, confidence, signals = classify("normativa/documento-general.md")
    assert role == "normative"
    assert confidence == "high"
    assert signals == ["folder:normativa"]


def test_folder_lexicon_example_family_classifies_unambiguously():
    role, confidence, signals = classify("ejemplos/muestra-final.pdf")
    assert role == "example"
    assert confidence == "high"


def test_folder_lexicon_evidence_family_classifies_unambiguously():
    role, confidence, signals = classify("evidencia/captura-01.png")
    assert role == "evidence"
    assert confidence == "high"


def test_folder_lexicon_matches_word_within_a_hyphenated_component():
    # design.md's own cited example: "guides/manual-estadia-tic/" ->
    # normative, via the "manual" word inside the hyphenated component.
    role, confidence, signals = classify("guides/manual-estadia-tic/00-intro.md")
    assert role == "normative"
    assert confidence == "high"
    assert signals == ["folder:manual"]


def test_folder_lexicon_is_case_folded():
    role, _confidence, _signals = classify("NORMATIVA/Reglas.md")
    assert role == "normative"


# --- filename-pattern signal (secondary, lower weight) --------------------


def test_filename_pattern_signal_classifies_when_folder_has_no_hit():
    # "Secondary, lower weight" (design.md): a filename-only match still
    # determines role, but with LOWER confidence than a folder match.
    role, confidence, signals = classify("misc/plantilla-informe.md")
    assert role == "example"
    assert confidence == "medium"
    assert signals == ["filename:plantilla"]


def test_filename_pattern_signal_weaker_than_folder_signal():
    folder_role, folder_confidence, _ = classify("normativa/doc.md")
    name_role, name_confidence, _ = classify("misc/manual-tecnico.md")
    assert folder_role == name_role == "normative"
    assert folder_confidence == "high"
    assert name_confidence == "medium"
    assert name_confidence != folder_confidence


def test_folder_and_filename_signals_combine_for_the_same_role():
    role, confidence, signals = classify("evidencia/captura-anexos.png")
    assert role == "evidence"
    assert confidence == "high"
    assert signals == ["folder:evidencia", "filename:anexos"]


# --- 8.2: ambiguous / unmatched sources are queued, not defaulted --------


def test_unmatched_path_yields_unknown_role_low_confidence_no_signals():
    role, confidence, signals = classify("misc/random-notes.txt")
    assert role == "unknown"
    assert confidence == "low"
    assert signals == []


def test_conflicting_signals_across_roles_yield_unknown_not_an_arbitrary_pick():
    # A path carrying EQUALLY-WEIGHTED signals for TWO different roles is
    # genuinely ambiguous -- spec: "Ambiguous source is queued, not
    # defaulted". Never silently prefer one role over another on a tie.
    # "manual" (normative) and "muestra" (example) both hit once in the
    # same folder component -> both score 0.5, a genuine tie.
    role, confidence, signals = classify("manual-muestra/doc.md")
    assert role == "unknown"
    assert confidence == "low"
    assert signals == []


def test_stronger_signal_for_one_role_wins_over_a_weaker_signal_for_another():
    # NOT a tie: "normativa" (folder, score 0.5) outweighs "ejemplo"
    # (filename-only, score 0.3) -- the stronger, unambiguous signal wins.
    role, confidence, _signals = classify("normativa/ejemplo-de-uso.md")
    assert role == "normative"
    assert confidence == "high"


def test_classify_is_a_pure_function_same_input_same_output():
    first = classify("evidencia/captura-01.png")
    second = classify("evidencia/captura-01.png")
    assert first == second
