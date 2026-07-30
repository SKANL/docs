# tests/unit/domain/test_source_role.py
"""Source-role classification (Front D, design.md Decision 4; spec:
document-ingest "Source-Role Classification"). Deterministic folder-name
lexicon (primary) + filename-pattern (secondary, lower weight) signals,
PLUS (PR4, item D) optional content signals (weaker than folder, stronger
than filename) fed in by an already-probed `ContentSignals` -- the pure
classifier never does I/O itself, it only scores strings it is handed.
`classify(relative_path, signals=None)` is a pure function: zero AI
judgment at runtime, pure data in, pure data out."""
from __future__ import annotations

from docs.domain.ports.content_probe_port import ContentSignals
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


# --- WARNING-1 / SUGGESTION-1: lexicon coverage for THIS repo's own -----
# --- real folder names (fresh-context verify, PR4 fix batch) ------------


def test_english_example_folder_name_classifies_via_folder_signal():
    # WARNING-1: reproduced against this repo's OWN fixture folder name
    # (example_tesina/, from reporte-estadia-tic.json's example_pdf path).
    # A generic filename with NO lexicon hit of its own must still resolve
    # via the folder-level "example" word.
    role, confidence, signals = classify("example_tesina/case-study.pdf")
    assert role == "example"
    assert confidence == "high"
    assert signals == ["folder:example"]


def test_english_example_folder_name_combines_with_filename_signal():
    # example_tesina/RE-Ejemplo.pdf (this repo's real fixture path):
    # now gets BOTH a folder hit ("example") and a filename hit
    # ("ejemplo") -- confidence rises from medium (filename-only, before
    # this fix) to high.
    role, confidence, signals = classify("example_tesina/RE-Ejemplo.pdf")
    assert role == "example"
    assert confidence == "high"
    assert signals == ["folder:example", "filename:ejemplo"]


def test_extracted_folder_name_classifies_as_evidence():
    # WARNING-1: reproduced against this repo's OWN fixture folder name
    # (extracted/, from reporte-estadia-tic.json's extracted_dir path, and
    # PR3's own realistic-drop acceptance test). "extracted" content is
    # plausibly always evidence/traceability material by construction.
    role, confidence, signals = classify("extracted/notes.md")
    assert role == "evidence"
    assert confidence == "high"
    assert signals == ["folder:extracted"]


def test_singular_anexo_recognized_alongside_plural_anexos():
    # SUGGESTION-1: only the plural "anexos" was in the EVIDENCE lexicon --
    # a singular folder name got zero signal.
    role, confidence, signals = classify("anexo/foto.png")
    assert role == "evidence"
    assert confidence == "high"
    assert signals == ["folder:anexo"]


# --- 4.1: `signals=None` default is a byte-for-byte regression guard -----


def test_classify_without_signals_arg_matches_default_none_explicitly():
    # `classify(path)` and `classify(path, signals=None)` MUST be identical
    # -- the new optional parameter must never change any existing caller's
    # behavior (task 4.1 regression guard; every test above already relies
    # on this since none of them pass `signals`).
    assert classify("normativa/reglas.md") == classify("normativa/reglas.md", signals=None)
    assert classify("misc/random-notes.txt") == classify("misc/random-notes.txt", signals=None)


# --- 4.2: content signals (item D) -- weaker than folder, stronger than --
# --- filename, deterministic string matching against the same lexicons --


def test_content_signal_alone_on_an_arbitrary_filename_reaches_high_confidence():
    # Two content-signal lexicon hits (0.4 each = 0.8) beat the 0.5 high
    # threshold on their own -- an arbitrarily-named file with strong
    # content signals is routed correctly (spec scenario: "High-confidence
    # classification acts automatically").
    role, confidence, signals = classify(
        "misc/9f3ac1.pdf", signals=ContentSignals(pdf_title="Manual de Normativa Interna")
    )
    assert role == "normative"
    assert confidence == "high"
    assert signals == ["content:manual", "content:normativa"]


def test_single_content_signal_hit_alone_yields_medium_confidence():
    # A single content hit (0.4) is weaker than a folder hit (0.5) but
    # present -- medium confidence, held for confirmation (never silently
    # promoted to high on a single weak signal).
    role, confidence, signals = classify(
        "misc/8b21ee.pdf", signals=ContentSignals(head_keywords=("referencia",))
    )
    assert role == "example"
    assert confidence == "medium"
    assert signals == ["content:referencia"]


def test_content_signal_combines_with_filename_signal_to_reach_high():
    # design.md ADR-D weighting: content (0.4) + filename (0.3) = 0.7 --
    # crosses the high threshold together even though neither alone would.
    role, confidence, signals = classify(
        "misc/referencia-2024.pdf", signals=ContentSignals(head_keywords=("ejemplo",))
    )
    assert role == "example"
    assert confidence == "high"
    assert signals == ["filename:referencia", "content:ejemplo"]


def test_content_signal_weaker_than_folder_signal():
    folder_role, folder_confidence, _ = classify("normativa/doc.md")
    content_role, content_confidence, _ = classify(
        "misc/doc.pdf", signals=ContentSignals(head_keywords=("manual",))
    )
    assert folder_role == content_role == "normative"
    assert folder_confidence == "high"
    assert content_confidence == "medium"


def test_content_signal_is_case_and_accent_folded():
    # Real PDF titles/headings carry Spanish accents; the classifier must
    # still match its ASCII lexicon (e.g. "guia" matches "GUÍA").
    role, confidence, _signals = classify(
        "misc/random.pdf", signals=ContentSignals(pdf_title="GUÍA Operativa")
    )
    assert role == "normative"
    assert confidence == "medium"


def test_evidence_content_keywords_ficha_and_empresa():
    role, confidence, signals = classify(
        "misc/001.pdf", signals=ContentSignals(head_keywords=("ficha", "empresa"))
    )
    assert role == "evidence"
    assert confidence == "high"
    assert signals == ["content:empresa", "content:ficha"]


def test_content_signal_conflicting_across_roles_yields_unknown_not_defaulted():
    # Equally-weighted content-only signals for two roles: still genuinely
    # ambiguous -- queued, never an arbitrary pick (spec: "Low-confidence
    # classification is held, not guessed").
    role, confidence, signals = classify(
        "misc/data.md", signals=ContentSignals(head_keywords=("manual", "referencia"))
    )
    assert role == "unknown"
    assert confidence == "low"
    assert signals == []


def test_folder_filename_and_content_signals_combine_in_stable_order():
    role, confidence, signals = classify(
        "normativa/manual.md", signals=ContentSignals(head_keywords=("normativa",))
    )
    assert role == "normative"
    assert confidence == "high"
    assert signals == ["folder:normativa", "filename:manual", "content:normativa"]
