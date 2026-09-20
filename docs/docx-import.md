# DOCX Import and PDF Edit Boundary

DOCX import is a structured projection into editable Markdown and extracted
assets. It preserves the original `source.docx` byte-for-byte for audit, but
it does **not** promise lossless OOXML round-tripping. Rendering a new DOCX
from the editable section is a separate, deterministic transform.

## Import categories

`DocxImportService` writes `import-report.json` beside `document.md`,
`source.docx`, and `assets/`. The report makes every compromise explicit:

| Category | Meaning | Examples |
|---|---|---|
| `preserved` | Source evidence or readable content retained in the projection | `source:exact-bytes`, `body:block-order`, `asset:embedded-image-bytes` |
| `normalized` | DOCX structure represented in the Markdown model | non-default paragraph styles become HTML comments; tables become Markdown tables |
| `dropped` | Content intentionally omitted from the editable projection | empty paragraphs |
| `unsupported` | OOXML parts detected but not projected | `ooxml-part:word/footnotes.xml`, comments, endnotes, custom XML, and glossary parts |

The source hash is SHA-256 and the output tree is deterministic for the same
source bytes. Paragraphs and tables retain document-body order. Images are
extracted to stable `assets/image-N.<ext>` names and remain editable through
their Markdown references. Unsupported parts are reported rather than
silently presented as preserved.

## Acceptance journey

`tests/integration/test_docx_pdf_edit_journey.py` exercises one bounded path:

1. Import a DOCX twice and assert equal reports, source bytes, and asset bytes.
2. Edit only the generated Markdown section; assert untouched prose, table
   content, and assets remain present.
3. Render the section through Pandoc, with the section directory supplied as a
   resource path, and reopen the DOCX to verify text, table, image, and audit
   evidence.
4. Convert the DOCX to PDF with LibreOffice, then replace one text run with
   `Pypdfium2TextEditAdapter`.
5. Verify the edited text, untouched text, page geometry, post-write bounds,
   and deterministic repeated edit bytes.
6. Record the source and derived artifacts in the provenance ledger and an
   evidence passport; both must verify on replay.

The real conversion/edit half is capability-gated because LibreOffice is an
external executable. When it is absent, the journey is skipped with the
capability named, while the companion assertion verifies that the PDF adapter
returns `None`, emits a `WARN`, and leaves no partial PDF. Draft pipeline runs
follow the same visible warning/skip rule; strict and release policies may
promote the missing capability to a blocking error.

This boundary verifies readable structure and bounded visual edits. It does
not claim preservation of arbitrary OOXML features, semantic PDF tagging,
or byte identity for LibreOffice-produced PDFs.
