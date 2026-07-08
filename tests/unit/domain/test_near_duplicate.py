# tests/unit/domain/test_near_duplicate.py
"""Near-duplicate detection (Front E, design.md Decision 5; spec:
document-ingest "Near-Duplicate Detection"). Deterministic 5-word-shingle
Jaccard similarity over normalized text (reusing
`markdown_text.clean_markdown_text`), fixed threshold `>= 0.85`, fidelity
ranking picks the kept member. Pure set math -- zero randomness, zero AI
judgment at runtime."""
from __future__ import annotations

from docs.domain.near_duplicate import SourceDoc, find_duplicates


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
