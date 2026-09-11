# Status: implemented — read `openspec/specs/document-translate/spec.md`, not this folder

The capability is built and green. **The authoritative contract is
`openspec/specs/document-translate/spec.md`.** `proposal.md`, `design.md` and
`tasks.md` here are the plan as written BEFORE implementation, kept for the
audit trail. Where they disagree with the spec or the code, they are wrong.

## Where reality diverged from the plan, and why

### 1. There is no LLM adapter. Translation is a cognitive slot.

The plan assumed a `TranslationPort` backed by a model API. This harness has
no LLM client anywhere and should not grow one — the model fills declared
slots in files and the harness does every mechanical step around them.

Translation follows that same contract:
`infrastructure/translate/pending_slot_translator.py` writes a
`<out>.pending.json` listing every block still needing a translation. The
first run still produces a complete document. Filling the file and re-running
produces the translated one, and every run after that is a cache hit.

This is a better fit for the goal than an API call would have been: a missing
or refused translation is structurally a MISS, so no engine's opinion can stop
the document.

### 2. `guarded_translate` grew `accept_unchanged`.

The plan rejected any response identical to its input, on the grounds that a
model echoing its input did not translate. True for a live engine, wrong for
a filled slot: "1", "ACME" and a code snippet are the same string in every
language. A real document reported `4/16` translated when all 16 were filled.
A live engine keeps the strict default; the slot translator sets the flag.

### 3. `block_grouping.py` was rewritten after looking at the output.

The planned version used fixed thresholds. Rendered on a real document it
produced three defects that every test passed:

- a fixed 2.0pt baseline tolerance split one line of 11pt text and emitted
  `"fi nance team Prepared by the"` — the words in the WRONG ORDER;
- with no horizontal-gap rule, seven chart axis labels became one block and
  were redrawn left-aligned in the corner;
- with no horizontal-overlap rule, a chart title at x=189 merged with an axis
  label at x=39.

Every threshold is now proportional to font size, and adjacent runs rejoin
without a space so a split ligature reads `"flat"` rather than `"fl at"`.

### 4. The 0.95 visual gate was withdrawn. It could not fail.

`design.md` ADR-8 claimed rendered similarity ≥0.95 would prove layout
preservation. Measured, mean pixel difference scored the layout-DESTROYED
page above **0.9905**: on a mostly-white page, averaging over every pixel
dilutes any disaster.

The replacement compares coarse ink DENSITY rather than pixels, which is the
right question — the glyphs are supposed to change, their position is not.
But even that scores destroyed **0.8015** against correct **0.8253**, and the
same correct translation of a sparse figure scores **0.60**. No threshold
between those is derivable rather than fitted to one sample.

So `page_similarity` is documented as a DIAGNOSTIC with a loose 0.5 collapse
floor, and the guarantee that actually ships is structural and exact: **every
non-text page object is preserved by kind and count**, provable because only
text objects are ever removed or inserted
(`test_pypdfium2_text_edit_adapter.py::test_non_text_objects_are_preserved_exactly`).

## What the plan got right and is worth keeping

ADR-1 (close the textpage before mutating, or PDFium silently destroys text
objects) and ADR-3 (normalize the random trailer `/ID`, or output is
non-deterministic) were both measured before implementation and both held
exactly. They are now in `CLAUDE.md` and mechanised by
`tests/architecture/test_pdf_writer_invariant.py`.

## Still out of scope

Multi-column reading order (reported as unverified, not guessed at), OCR for
scanned PDFs (refused with a clear reason), non-Latin target scripts (base-14
fonts have no coverage), table and form cell boundaries, and input formats
other than PDF.
