# Docs Harness v2 Templates and Portability

A v2 document still uses the existing data-only template model. The template, document configuration, sections, context, and assets are source inputs; the v2 runtime adds contracts and evidence around them without requiring a new template language.

## Template inputs

Create and validate templates with the native commands:

```bash
uv run docs template init informe-tecnico
uv run docs template validate informe-tecnico
```

A template declares structure, section contracts, context schema, citation policy, page geometry, strict-mode policy, and optional output/template-contract details. `document create` copies the template structure into the document; later template edits do not silently change an existing document's frozen structure. Use the document's `document.json` or create a new document when structure must change.

Sections remain the only prose authoring slot. The harness may ingest and normalize source material, but it never copies source text into authored section bodies. Use symbolic figure/table markers and let the build number them.

## Portability boundary

The core runtime is Python 3.11+ with `uv`. It uses local ports and injected adapters. Optional executable capabilities are checked with `PATH` and appear in `document status --json` and runtime reports. The v2 CLI does not require Documents, PDF, Template Creator, or any other external plugin at runtime.

| Capability | Used for | Draft behavior when absent |
|---|---|---|
| `pandoc` | DOCX/HTML conversion | Requested format may warn/skip according to renderer contract. |
| LibreOffice | PDF conversion and visual checks | PDF/visual work may be skipped or warned. |
| Java | Some PDF ingest paths | Those source paths may be skipped. |
| `mmdc` | Mermaid visuals | That visual is skipped. |
| `resvg` | SVG rasterization | That figure is skipped. |

Strict/release policies turn missing required capabilities into errors. A plugin can help author or inspect documents, but it is not a runtime dependency and cannot supply the native v2 contract, provenance, or publication gate.

## Reproducibility

DOCX and HTML are deterministic for identical source/template/configuration/toolchain identities. PDF is derived through LibreOffice and is not byte-deterministic across renderer versions. Renderer identities are captured in the build manifest so a later publish detects drift.

## Adding a template

Keep templates data-only, validate them with the native CLI, and test at least one prepare/build/verify path. Do not add Python code or a plugin solely to declare sections, context, or review rules. If a template requires a new renderer or capability, document the capability and its draft/strict/release policy explicitly.
