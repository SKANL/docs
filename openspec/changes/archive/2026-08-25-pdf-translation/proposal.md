# Proposal: PDF Translation (`document-translate`)

## Why

The harness can *create* documents. It cannot *translate* one it did not
author. Translating a PDF is the opposite problem from generating one: we do
not own the content, and the layout is someone else's contract that we must
honour.

The user-facing promise is deliberately unconditional: **if a user asks for a
translation, it translates.** No topic gating, no refusals, no "I'd rather
not." A translator that declines is a broken tool, and a model's opinion is
never allowed to become the harness's behaviour.

## What changes

A new capability, `document-translate`, with one CLI command:

    docs translate <input.pdf> --to <lang> [--from auto] [--out <path>]

Output is a PDF with the same page count, the same geometry, the same images
and vectors, and the text replaced in place by its translation.

## Scope

**Phase 1 (this change)** — single-column, text-based PDFs. Block-level
translation, layout preserved with shrink-then-wrap fitting, deterministic
byte-identical reruns, and a mechanical visual-similarity gate.

**Phase 2** — multi-column and complex layouts, using `pdf-inspector`
reading order.

**Phase 3** — scanned/image PDFs via OCR.

**Phase 4** — other input formats (DOCX, Markdown) reusing the same
`TranslationPort` and translation memory.

Phases 2-4 are named so Phase 1 does not accidentally design them out. They
are not built here.

## The honest ceiling

"Looks exactly the same, only translated" is **not** achievable at 100%, and
saying otherwise sells what the format cannot do:

- Text expands. EN->ES runs ~20-25% longer. It does not fit the original box.
- Embedded fonts ship as **subsets** containing only the glyphs the document
  already used. A target-language glyph that was never used is simply absent.
  This is the repo's own recurring lesson: *present is not usable*.

What we deliver instead, and what Phase 1's gate measures: same page count,
same page geometry, images and vector art untouched, every text block inside
its original bounding box, fitted by shrink-then-wrap. Target: >=0.95
structural similarity on the rendered page. Anything that cannot be fitted or
whose font had to be substituted is **counted and reported**, never silently
absorbed.

## Impact

- New capability spec: `openspec/specs/document-translate/spec.md`
- New ports: `PdfTextEditPort`, `TranslationPort`, `TranslationMemoryPort`
- New dependency: `pdf-inspector` (Rust, **MIT**, Python bindings) for PDF
  classification. `pypdfium2` is already declared and needs no addition.
- New pipeline stage set: `translate`
- No change to any existing capability. Translation is a separate entry
  point, not a mutation of the authoring pipeline.
