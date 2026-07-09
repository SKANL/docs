# tests/unit/domain/test_near_duplicate.py
"""Near-duplicate detection (Front E, design.md Decision 5; spec:
document-ingest "Near-Duplicate Detection"). Deterministic 5-word-shingle
Jaccard similarity over normalized text (reusing
`markdown_text.clean_markdown_text` + `strip_frontmatter_and_markdown`),
fixed threshold `>= 0.85`, fidelity ranking picks the kept member. Pure set
math -- zero randomness, zero AI judgment at runtime.

Hardened (fresh-context verify, PR4 fix batch, CRITICAL-1 + WARNING-2): the
normalization pipeline previously never folded accents or stripped
markdown structural markup (headings/lists/blockquotes/tables), so an
accented hand-curated file vs an unaccented/markup-noisy OCR-style
extraction of the SAME content could score as low as jaccard~0.12 --
silently missing the exact real-world scenario this feature exists for."""
from __future__ import annotations

import unicodedata

from docs.domain.near_duplicate import SourceDoc, find_duplicates


def _strip_accents(text: str) -> str:
    """Test-local accent stripper, deliberately INDEPENDENT from
    production code (`docs.domain.markdown_text._ACCENT_TRANSLATION`) --
    verifies the fix's OBSERVABLE BEHAVIOR (detects despite accent
    divergence), not a specific implementation detail."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# --- 9.1: Jaccard threshold boundary --------------------------------------


def test_identical_text_is_flagged_a_near_duplicate():
    text = "Esta es una guía de referencia para la elaboración del reporte de estadía."
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=text),
        SourceDoc(relative_path="b.md", kind="txt", text=text),
    ]
    decisions = find_duplicates(docs)
    assert len(decisions) == 1
    assert decisions[0].jaccard == 1.0


def test_near_duplicate_with_one_edit_is_flagged_above_threshold():
    # 80 distinct words -> 76 overlapping 5-word shingles; changing ONE word
    # near the middle only perturbs the 5 shingles that window over it, so
    # Jaccard = (76-5)/(76+76-71) ~= 0.8765, comfortably above the 0.85
    # threshold -- a single realistic edit must not fall out of "near".
    base_words = [f"palabra{i}" for i in range(1, 81)]
    base = " ".join(base_words)
    edited_words = list(base_words)
    edited_words[39] = "diferente"
    edited = " ".join(edited_words)
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=base),
        SourceDoc(relative_path="b.md", kind="pdf", text=edited),
    ]
    decisions = find_duplicates(docs)
    assert len(decisions) == 1
    assert decisions[0].jaccard >= 0.85


def test_disjoint_texts_are_not_flagged_as_duplicates():
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text="Contenido completamente distinto sobre historia."),
        SourceDoc(relative_path="b.md", kind="md", text="Otro tema totalmente diferente sobre biología marina."),
    ]
    assert find_duplicates(docs) == []


def test_texts_just_below_threshold_are_not_flagged():
    # Two 20-word texts sharing only the first 8 words -- shingle overlap
    # stays comfortably under the 0.85 threshold.
    base = "uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince"
    other = "uno dos tres cuatro cinco seis siete ocho zzz yyy xxx www vvv uuu ttt"
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=base),
        SourceDoc(relative_path="b.md", kind="md", text=other),
    ]
    assert find_duplicates(docs) == []


# --- CRITICAL-1 / WARNING-2: accent + markdown-structure normalization ---


def test_accent_and_markup_divergent_curated_vs_extracted_text_is_detected_as_near_duplicate():
    # CRITICAL-1 regression proof (fresh-context verify, PR4 fix batch):
    # a hand-curated markdown file (correct Spanish accents) vs a
    # plausible OCR/PDF-extraction variant of the SAME underlying content
    # (accents stripped -- a well-known extraction artifact category --
    # PLUS markdown structural noise, PLUS one genuinely different word)
    # must still be detected as a near-duplicate. Before the fix, accent
    # divergence alone made virtually every 5-word shingle differ (Spanish
    # prose is accent-dense), scoring jaccard ~0.12 -- nowhere near the
    # threshold, and the duplicate went undetected, silently.
    curated_words = [
        "La", "guía", "de", "referencia", "para", "la", "elaboración", "del",
        "reporte", "de", "estadía", "técnica", "describe", "el", "proceso",
        "completo", "que", "sigue", "el", "estudiante", "durante", "su",
        "período", "de", "vinculación", "profesional", "con", "la",
        "organización", "receptora", "y", "detalla", "cada", "sección",
        "obligatoria", "del", "documento", "final", "incluyendo",
        "introducción", "metodología", "y", "conclusiones", "además",
        "explica", "los", "criterios", "de", "evaluación", "académica",
        "aplicados", "por", "el", "asesor", "y", "el", "comité",
        "correspondiente", "a", "lo", "largo", "de", "todo", "el",
        "período", "formativo", "institucional", "reconocido", "por", "la",
        "universidad", "y", "sus", "programas", "de", "vinculación",
        "empresarial", "vigentes", "actualmente",
    ]
    curated_text = " ".join(curated_words)

    extracted_words = [_strip_accents(word) for word in curated_words]
    # A genuine OCR/extraction content variation, not just accent
    # stripping -- one word actually differs.
    extracted_words[15] = "diferente"
    extracted_text = "# " + " ".join(extracted_words)
    extracted_text = extracted_text.replace("tecnica", "**tecnica**", 1)

    docs = [
        SourceDoc(relative_path="curated.md", kind="md", text=curated_text),
        SourceDoc(relative_path="extracted.md", kind="pdf", text=extracted_text),
    ]

    decisions = find_duplicates(docs)

    assert len(decisions) == 1
    assert decisions[0].jaccard >= 0.85
    assert decisions[0].kept == "curated.md"
    assert decisions[0].superseded == "extracted.md"


def test_markdown_structural_markup_divergence_does_not_prevent_near_duplicate_detection():
    # WARNING-2 (fresh-context verify, PR4 fix batch): heading (#),
    # list (-), blockquote (>), and table (|) markup are NOT stripped by
    # clean_markdown_text alone -- only bold/italic/code markers are.
    # Heavy structural markup on one side must not drag a genuinely
    # similar document below threshold.
    plain_words = [f"palabra{i}" for i in range(1, 81)]
    plain_text = " ".join(plain_words)
    structured_words = list(plain_words)
    structured_words[39] = "diferente"
    structured_text = (
        "# Encabezado\n\n"
        + "- " + " ".join(structured_words[:20]) + "\n"
        + "> " + " ".join(structured_words[20:40]) + "\n"
        + "| " + " ".join(structured_words[40:]) + " |"
    )
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=plain_text),
        SourceDoc(relative_path="b.md", kind="pdf", text=structured_text),
    ]

    decisions = find_duplicates(docs)

    assert len(decisions) == 1
    assert decisions[0].jaccard >= 0.85


# --- WARNING-3: sub-shingle-size documents (documented, pinned) ---------


def test_short_documents_below_shingle_size_can_only_be_exact_or_disjoint():
    # WARNING-3 (fresh-context verify, PR4 fix batch): documented,
    # deliberate behavior, NOT changed by this fix batch -- a document
    # shorter than the 5-word shingle size collapses to a SINGLE whole-text
    # shingle, so it can only ever match EXACTLY (jaccard=1.0) or be
    # entirely DISJOINT (jaccard=0.0) against another short document; there
    # is no graduated "near" match possible below the shingle-size
    # threshold. Safe (never a FALSE duplicate flag), but zero fuzzy-match
    # value for short files. Pinned here so a future change to this
    # boundary is a conscious, tested decision.
    identical = [
        SourceDoc(relative_path="a.md", kind="md", text="hola mundo pequeño"),
        SourceDoc(relative_path="b.md", kind="md", text="hola mundo pequeño"),
    ]
    assert find_duplicates(identical)[0].jaccard == 1.0

    near_but_short = [
        SourceDoc(relative_path="a.md", kind="md", text="hola mundo pequeño"),
        SourceDoc(relative_path="b.md", kind="md", text="hola mundo pequeño extra"),
    ]
    assert find_duplicates(near_but_short) == []


# --- SUGGESTION-2: empty documents are never comparable ------------------


def test_two_empty_documents_are_not_flagged_as_duplicates_of_each_other():
    # SUGGESTION-2 (fresh-context verify, PR4 fix batch): two genuinely
    # empty ingested outputs (e.g. failed/blank conversions) have no real
    # content to compare -- must NOT be flagged as 100% duplicates of each
    # other. Skipped from the pairwise pass entirely.
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=""),
        SourceDoc(relative_path="b.md", kind="pdf", text="   \n\t  "),
    ]
    assert find_duplicates(docs) == []


def test_empty_document_is_not_flagged_against_a_non_empty_one_either():
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text=""),
        SourceDoc(relative_path="b.md", kind="md", text="Contenido real con suficiente longitud."),
    ]
    assert find_duplicates(docs) == []


# --- 9.2: fidelity ranking --------------------------------------------


def test_fidelity_ranking_prefers_curated_md_over_pdf_extracted_regardless_of_order():
    text = "Contenido idéntico entre la copia curada y la copia extraída del PDF original."
    curated = SourceDoc(relative_path="curated.md", kind="md", text=text)
    pdf_extracted = SourceDoc(relative_path="extracted.md", kind="pdf", text=text)

    decisions_a = find_duplicates([curated, pdf_extracted])
    decisions_b = find_duplicates([pdf_extracted, curated])

    assert decisions_a[0].kept == "curated.md"
    assert decisions_a[0].superseded == "extracted.md"
    assert decisions_b[0].kept == "curated.md"
    assert decisions_b[0].superseded == "extracted.md"


def test_fidelity_ranking_full_order_curated_over_docx_over_pdf_over_txt():
    text = "Texto idéntico repetido en las cuatro variantes de fidelidad distinta."
    curated = SourceDoc(relative_path="c.md", kind="md", text=text)
    docx = SourceDoc(relative_path="d.md", kind="docx", text=text)
    pdf = SourceDoc(relative_path="p.md", kind="pdf", text=text)
    txt = SourceDoc(relative_path="t.md", kind="txt", text=text)

    assert find_duplicates([txt, pdf, curated])[0].kept == "c.md"
    assert find_duplicates([txt, pdf, docx])[0].kept == "d.md"
    assert find_duplicates([txt, pdf])[0].kept == "p.md"


def test_fidelity_tie_break_by_posix_relative_path():
    text = "Mismo contenido, misma fidelidad de origen, dos rutas distintas."
    a = SourceDoc(relative_path="folder-a/doc.md", kind="md", text=text)
    b = SourceDoc(relative_path="folder-b/doc.md", kind="md", text=text)

    decisions_forward = find_duplicates([a, b])
    decisions_reversed = find_duplicates([b, a])

    assert decisions_forward[0].kept == "folder-a/doc.md"
    assert decisions_reversed[0].kept == "folder-a/doc.md"


def test_distinct_sources_are_not_falsely_merged_regardless_of_fidelity():
    docs = [
        SourceDoc(relative_path="a.md", kind="md", text="Un tema completamente distinto sobre cocina."),
        SourceDoc(relative_path="b.md", kind="pdf", text="Un tema completamente distinto sobre astronomía."),
    ]
    assert find_duplicates(docs) == []
