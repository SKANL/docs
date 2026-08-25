# Design: PDF Translation

## Spike results (measured, not assumed)

Everything below was proven against a real PDF before this design was
written. Scripts: scratchpad `spike.py` / `spike2.py` / `diag.py`.

| Question | Answer |
|---|---|
| Can `pypdfium2` replace PDF text in place? | **Yes.** All 18 required raw symbols present in PDFium 153.0.7999.0. No PyMuPDF, no AGPL, no new dependency. |
| Can we read text + bbox + font size per object? | **Yes.** `FPDFTextObj_GetText`, `FPDFPageObj_GetBounds`, `FPDFTextObj_GetFontSize`. |
| Is the output deterministic? | **No, and the cause is exact.** See ADR-3. |
| Does a longer translation survive the round trip? | **Yes.** `"Hello world"` -> `"Hola mundo entero"` read back correctly. |

### ADR-1: The textpage MUST be closed before mutating the page

**This is a silent data-destroying bug, and it is easy to write.**

Holding an open textpage (`FPDFText_LoadPage`) while calling
`FPDFPage_RemoveObject` / `FPDFPage_InsertObject` / `FPDFPage_GenerateContent`
**destroys unrelated text objects with no error raised.**

Measured: a 3-object page (1 path + 2 text) came back as 2 objects. One text
run vanished entirely. `FPDFPage_CountObjects` went 3 -> 2 and nothing threw.

The adapter is therefore split into two strictly ordered phases:

    READ  phase: FPDFText_LoadPage ... collect everything ... FPDFText_ClosePage
    WRITE phase: Remove / Destroy / Insert / GenerateContent / save

`FPDFPage_RemoveObject` transfers ownership to the caller, so every removal
is paired with `FPDFPageObj_Destroy`.

After the fix: 3 objects in, 3 objects out, both text runs translated.

### ADR-2: The block is the unit of both translation and layout

Translating one PDF text object at a time produces fragment translation
("Hello" and "world" as separate calls) and reads terribly.

Instead: group text objects into **blocks** by geometry, translate the block
as one string, then **remove every object in the block and lay out fresh
ones inside the block's bounding box.**

Because we control the write, we never need a 1:1 mapping from source object
to translated object. The block bbox is the layout contract; inside it we are
free to break lines however the text needs. This is both simpler and higher
quality than per-object replacement.

### ADR-3: `/ID` normalization is the PDF's `normalize_docx_zip_timestamps`

PDFium writes a **random file `/ID`** into the trailer on every save. Two
runs over identical input produced identical 1758-byte files whose only
difference was at offset 1662: the trailer `/ID` array. `/CreationDate` is
inherited from the source and is stable.

This is the exact shape of the `.docx` zip-timestamp problem this repo
already solved. A byte-identity test that fails here is a **product bug, not
test flake.**

Fix: rewrite both `/ID` hex strings with a content-derived SHA-256 of the
**same length**. Same length in, same length out, so the xref byte offsets
stay valid. Verified: byte-identical after normalization, file still opens
and reads back correctly.

Every PDF writer in this capability MUST end in
`normalize_pdf_id`, mechanised by an architecture test the same way
`test_docx_writer_invariant.py` guards the zip normalizer.

### ADR-4: Determinism comes from the cache, not the model

An LLM is not deterministic — batching, model versions and tie-breaks all
move the output. This harness requires byte-identical reruns.

So the translation memory *is* the determinism. Key:

    sha256(block_text + target_lang + source_lang + engine_id + glossary_version)

First run translates and caches. Every later run is a cache hit and produces
identical bytes for free. The TM lives in `translations/` as content-addressed
JSON, committed with the workspace.

### ADR-5: The model never gets a vote

Two independent layers, because one is not enough:

1. **The model never sees "a document."** It sees one text block and a target
   language — a structured cognitive slot, exactly as every other model call
   in this harness works.
2. **Harness rule, not model instruction:** a block that comes back empty, or
   refused, or byte-identical to its input in a different-script language pair
   gets **one** retry. If that fails, the **original text passes through**
   and the block is counted. The pipeline reports
   `traducido: 412/418 bloques (6 sin traducir)` in its own line.

The run **never aborts on a model's opinion.** A refusal degrades one block,
not the document.

### ADR-6: `pdf-inspector` is the classifier, `pypdfium2` is the editor

`pdf-inspector` (Rust, **MIT**, PDFium-backed) cannot write PDFs. It is used
for what it is uniquely good at:

- `pdf_type` -> `"text_based" | "scanned" | "image_based" | "mixed"`
- `pages_needing_ocr`, `has_encoding_issues`, `pages_with_columns`, `confidence`

Phase 1 does its own geometric block grouping from `pypdfium2` objects, which
avoids any join between two libraries' coordinate spaces. That grouping is
reliable for single-column and **unreliable for multi-column** — so
`pages_with_columns` is used as a loud degradation signal, not ignored.
Phase 2 replaces our grouping with `pdf-inspector` reading order.

### ADR-7: Font substitution is measured, not hidden

Original fonts are subsets and will lack target-language glyphs. Phase 1 maps
the original family onto a base-14 standard font
(`FPDFText_LoadStandardFont`), falling back to Helvetica. Phase 1 **always**
substitutes, and every block is counted as such: the number is meant to look
large, because that is the honest size of the compromise.

**Measured, and it bit once already:** `FPDFFont_GetFamilyName` is present,
returns success, and yields an **empty string** for embedded subset fonts
(length 1 — just the terminator — on a matplotlib PDF). Use
`FPDFFont_GetBaseFontName` instead, which returns `GGKEDP+DejaVuSans`. A
silently empty family would send every serif document back as sans and fail
the ADR-8 gate for a reason nobody could see.

That `GGKEDP+` prefix is the standard six-letter subset tag, and it is direct
evidence of the ceiling described in `proposal.md`: the embedded font holds
only the glyphs the document already used. Strip the tag, keep the family.

Third instance this session of *present is not usable*, after ADR-1 and
ADR-3.

### ADR-8: "Looks the same" is a number, not an opinion

`Pdfium2PdfRenderAdapter.render_pages()` already rasterizes PDF pages to PNG.
Reuse it: render original page N and translated page N, diff the images,
compute a similarity score, and fail the gate below a threshold.

This is the highest-value reuse in the whole change. It converts the headline
promise from something a human eyeballs into something CI enforces.

## Architecture

    cli/commands/translate.py
        -> application/translate.py        TranslateService
              -> PdfClassifyPort           pdf-inspector adapter
              -> PdfTextEditPort           pypdfium2 raw adapter (READ/WRITE phases)
              -> TranslationPort           LLM adapter
              -> TranslationMemoryPort     filesystem content-addressed cache
              -> PdfRenderPort             EXISTING - visual verification
        -> domain/
              block_grouping.py            pure geometry: objects -> blocks
              text_fitting.py              pure: shrink-then-wrap into a bbox
              pdf_id.py                    normalize_pdf_id

Dependency direction unchanged: cli -> application -> domain, infrastructure
implements ports, adapters wired only in `cli/_shared.py`.
