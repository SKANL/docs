# Document Translate Specification

## Purpose

Translate an existing PDF into a target language while preserving its layout, unconditionally and deterministically, so a user who asks for a translation always receives a complete document.

Implemented by `TranslateService` over the `PdfClassifyPort`, `PdfTextEditPort`, `TranslationPort` and `TranslationMemoryPort` ports. Blocking is owned by `group_runs_into_blocks`, layout by `fit_text_to_block`, the never-refuse rule by `guarded_translate`, cache identity by `memory_key`, output determinism by `normalize_pdf_id`, and layout verification by `page_similarity`.

This capability is a separate entry point, not a mutation of the authoring pipeline: it consumes documents the harness did not write.

## Requirements

### Requirement: Unconditional Translation

The system MUST NOT gate translation on content, topic, or provenance. A translation engine that refuses, returns nothing, returns the input unchanged, or raises MUST degrade exactly one block and MUST NOT abort the run.

#### Scenario: Engine refuses a block

- GIVEN a translation engine that answers a block with a refusal
- WHEN translation runs
- THEN the original text of that block is written into the output document
- AND the block is counted as untranslated
- AND a complete output PDF is still produced

#### Scenario: Engine raises an exception

- GIVEN a translation engine that raises on every call
- WHEN translation runs
- THEN no exception escapes to the caller
- AND a complete output PDF is still produced with every block in its source language

#### Scenario: Engine answers after one retry

- GIVEN an engine that returns an empty string once and a translation on the next call
- WHEN translation runs
- THEN the retried translation is used
- AND the engine is called exactly twice for that block

#### Scenario: A refusal is never cached

- GIVEN a block whose engine response is a refusal
- WHEN translation runs
- THEN nothing is written to the translation memory for that block
- AND a later run with a working engine can still translate it

### Requirement: Layout Preservation

The system MUST preserve page count and page geometry, MUST leave images and vector art untouched, and MUST lay translated text out within the bounding box of the source block it replaces.

#### Scenario: Page count is unchanged

- GIVEN a source PDF of N pages
- WHEN translation completes
- THEN the output PDF has exactly N pages

#### Scenario: Longer translation is fitted, not clipped

- GIVEN a translated block whose text is longer than its source
- WHEN the text is laid out
- THEN it is wrapped onto additional lines within the block's bounding box
- AND the font is shrunk only as far as the configured minimum scale

#### Scenario: Unrelated text objects survive an edit

- GIVEN a page holding several text objects
- WHEN one block is replaced
- THEN every text object outside that block is present and unchanged in the output

### Requirement: Deterministic Output

Two runs over identical input with a warm translation memory MUST produce byte-identical output PDFs.

#### Scenario: Warm cache reproduces bytes

- GIVEN a document already translated once, with its translations in the memory
- WHEN the same command is run twice more
- THEN both outputs are byte-identical to each other

#### Scenario: Random file identifier is normalized

- GIVEN the PDF writer, which stamps a random trailer `/ID` on every save
- WHEN the document is written
- THEN the `/ID` is replaced by a content-derived digest of the same byte length
- AND the resulting file still opens and reads back correctly

#### Scenario: Cache identity includes the target language

- GIVEN a block already translated into one language
- WHEN the same block is translated into a different language
- THEN the stored entry is not reused and the engine is called again

### Requirement: One Translation Per Identical Source

Blocks whose source text is identical MUST share a single translation within a document, and MUST be requested from the engine only once.

This follows from the translation memory being content-addressed, which is what makes reruns byte-identical. It is also correct on its own terms: the same heading rendered two different ways in one document is an inconsistency. The accepted cost is that a string needing different translations in different contexts cannot receive them; segment context is the upgrade path.

#### Scenario: A repeated string is asked for once

- GIVEN a source PDF in which the same text appears in two places
- WHEN the blocks needing translation are listed
- THEN that text appears exactly once in the list

#### Scenario: A repeated string is translated everywhere it appears

- GIVEN a translation supplied for a text that appears twice
- WHEN the document is written
- THEN both occurrences carry that translation

### Requirement: Honest Degradation

Untranslated blocks, overflowed blocks, substituted fonts, and pages whose block grouping is unverified MUST each be counted and reported in the command's own output line, never only in a file the reader must open.

#### Scenario: Compromises appear in the command output

- GIVEN a run in which some blocks were not translated and some did not fit
- WHEN the command finishes
- THEN its output line names the translated count, the untranslated count, the overflow count, and the substituted-font count

#### Scenario: Overlapping text is detected and its pages named

- GIVEN a block whose translation needs more lines than its source
- WHEN the laid-out text would reach into the block below it
- THEN that page is named in the command's output line before the document is written

#### Scenario: A dialogue label beside its speech is not a collision

- GIVEN two blocks on the same visual line whose bounding boxes overlap
- WHEN collisions are counted
- THEN they are not reported, because they are one line rather than stacked lines

#### Scenario: Multi-column pages are reported as unverified

- GIVEN a source PDF whose classifier reports pages with columns
- WHEN translation runs
- THEN those page numbers are reported as unverified rather than presented as a confident result

### Requirement: No Text Layer

A PDF with no text layer MUST be refused with a message naming OCR as the remedy, and MUST NOT be silently half-translated.

#### Scenario: Scanned PDF is refused

- GIVEN a source PDF classified as scanned or image-based
- WHEN translation is attempted
- THEN the command fails with a message stating the PDF has no text layer and that OCR is required
- AND no output document is written

#### Scenario: Mixed PDF is translated

- GIVEN a source PDF classified as mixed, which does carry a text layer
- WHEN translation runs
- THEN its text blocks are translated normally

### Requirement: Structural Preservation

The system MUST leave every non-text page object untouched. This is asserted structurally — by object kind and count — not estimated from rendered pixels, because only text objects are ever removed or inserted.

#### Scenario: Images and vector art survive a translation

- GIVEN a source PDF containing paths, images, or chart geometry
- WHEN its text blocks are translated and rewritten
- THEN the count and kind of every non-text page object is identical in the output

#### Scenario: A block is never split across pages

- GIVEN runs at the same coordinates on two different pages
- WHEN blocks are formed
- THEN no block contains runs from more than one page

### Requirement: Layout Collapse Detection

The system MUST provide a rendered-page comparison that detects total layout collapse. It MUST NOT be presented as a fidelity score.

Measured on a real document, a layout-destroyed page scored 0.8015 and a correct translation scored 0.8253, while the same correct translation of a sparse figure scored 0.60. No threshold between those values is derivable rather than fitted, so the comparison is a diagnostic with a loose collapse floor, and the exact guarantees live in Structural Preservation above.

#### Scenario: Identical pages score 1.0

- GIVEN two renders of the same page
- WHEN they are compared
- THEN the score is 1.0

#### Scenario: A changed page size is a total failure

- GIVEN two rendered pages of different dimensions
- WHEN they are compared
- THEN the score is 0.0 rather than an averaged partial score

#### Scenario: A wholly different page is detected

- GIVEN two pages whose ink shares no common region
- WHEN they are compared
- THEN the score is below 0.5
