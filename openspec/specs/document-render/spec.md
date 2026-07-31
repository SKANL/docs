# Document Render Specification

## Purpose

Provide a `DocumentRendererPort` abstraction resolved by target output format, with DOCX as the primary adapter, and prove the port is genuinely extensible to other formats without modifying domain/pipeline code.

## Requirements

### Requirement: Renderer Port Abstraction

The system MUST expose a `DocumentRendererPort` with a defined contract that any output-format renderer implements.

#### Scenario: DOCX adapter implements the port

- GIVEN the DOCX renderer adapter
- WHEN it is registered against `DocumentRendererPort`
- THEN it satisfies the port's contract and can render a document

### Requirement: Format-Registry Resolution at Composition Root

The system MUST resolve the concrete renderer from the configured output format at the composition root; domain/pipeline code MUST NOT branch on format.

#### Scenario: Resolve DOCX from config

- GIVEN a template/config specifying output format "docx"
- WHEN the pipeline resolves a renderer
- THEN the DOCX adapter is selected via the format registry

#### Scenario: Unregistered format

- GIVEN a config specifying a format with no registered renderer
- WHEN the pipeline resolves a renderer
- THEN the system raises a clear error naming the unsupported format
- AND does not silently fall back to DOCX

### Requirement: Extensibility Proof via Test Fake

The system MUST include at least one test-only fake renderer for a second format, proving the port is swappable without modifying domain/pipeline code.

#### Scenario: Fake renderer proves extensibility

- GIVEN a test-only fake renderer registered for a second format (e.g., "txt")
- WHEN the pipeline renders using that format
- THEN rendering succeeds through the fake
- AND no changes to `domain/pipeline.py` were required to support it

### Requirement: Config-Driven Assemble Stage Plan

The assemble stage plan MUST be derived from configuration per target format rather than hardcoded to a single document type.

#### Scenario: Assemble stages adapt to format

- GIVEN a config targeting DOCX output
- WHEN the assemble stage plan is built
- THEN it includes DOCX-specific stages (e.g., build, format-audit, QA) as configured for that format

#### Scenario: Second format yields a distinct stage plan

- GIVEN a config targeting a registered non-DOCX format
- WHEN the assemble stage plan is built
- THEN it reflects that format's configured stages, distinct from the DOCX plan

### Requirement: Document-Order Figure/Table Numbering at Build Time

The system MUST assign figure/table numbers automatically, in document order, at build/assemble time. Authors MUST use stable symbolic labels/anchors and "Ver {ref}"-style references in section Markdown; the build MUST resolve these to concrete numbers and cross-references. Authors and agents MUST NOT be required to hand-assign or hand-renumber `Figura N`/`Tabla N`.

#### Scenario: Figures numbered in document order

- GIVEN sections referencing figures via symbolic labels, in a known document order
- WHEN the document is built
- THEN each figure receives a sequential number matching its position in document order

#### Scenario: Cross-reference resolves to the assigned number

- GIVEN a section containing "Ver {ref}" pointing to a symbolic figure label
- WHEN the document is built
- THEN the reference resolves to the figure's assigned number (e.g., "Ver Figura 3")

#### Scenario: Reordering sections renumbers without manual edits

- GIVEN a document previously built with figures numbered per the original section order
- WHEN sections are reordered and the document is rebuilt with no manual number edits
- THEN figures are renumbered to match the new document order
- AND all "Ver {ref}" cross-references still resolve correctly

#### Scenario: Unresolvable reference is reported, not silently dropped

- GIVEN a "Ver {ref}" pointing to a label with no matching figure/table
- WHEN the document is built
- THEN the build reports a clear error naming the unresolved label

### Requirement: Evidence-Aware Review Precision

Review heuristics (subjective-word checks, required-content keyword checks, contested-stack-term checks) MUST require concrete evidence in context before flagging, so legitimate terms (e.g., a project genuinely using "Firebase") and legitimate subjective/plural-token usage are not flagged as violations while genuine issues are still caught.

#### Scenario: Legitimate stack term not flagged

- GIVEN a section using a technology term (e.g., "Firebase") that matches the actual project's ingested facts
- WHEN `review-section` runs
- THEN no contested-stack-term finding is raised for that term

#### Scenario: Genuinely contested/conflicting stack term still flagged

- GIVEN a section using a technology term that conflicts with the ingested facts about the project's actual stack
- WHEN `review-section` runs
- THEN a contested-stack-term finding is raised, naming the conflict

#### Scenario: Subjective-word check requires context, not bare substring

- GIVEN a section using a word from the subjective-word list in a non-subjective, evidenced context
- WHEN `review-section` runs
- THEN it is not flagged as an unsupported subjective claim

### Requirement: Deterministic HTML Renderer

The system MUST implement `DocumentRendererPort` for the `html` format (pandoc-backed), registered in the format registry, producing byte-identical output for unchanged Markdown sources and configuration.

#### Scenario: HTML renderer registered

- GIVEN the format registry
- WHEN resolving a renderer for `html`
- THEN the pandoc-backed HTML adapter is returned

#### Scenario: HTML output is byte-deterministic

- GIVEN unchanged section Markdown and configuration
- WHEN the HTML document is built twice
- THEN the two HTML files are byte-identical

### Requirement: Best-Effort PDF Renderer With Graceful Degradation

The system MUST implement `DocumentRendererPort` for the `pdf` format (soffice/pandoc-backed). PDF output MUST NOT be required byte-deterministic. When the PDF toolchain is unavailable, the system MUST WARN and skip PDF generation rather than hard-failing the build.

#### Scenario: PDF renders when toolchain present

- GIVEN `soffice` or a PDF-capable `pandoc` path is available
- WHEN a build requests `pdf` output
- THEN a PDF artifact is produced via the format registry

#### Scenario: PDF toolchain absent warns and skips

- GIVEN neither `soffice` nor a PDF-capable `pandoc` path is available
- WHEN a build requests `pdf` output
- THEN the system WARNs naming the missing toolchain, skips the PDF artifact, and other requested formats still succeed

#### Scenario: PDF output is not byte-deterministic

- GIVEN unchanged section Markdown and configuration
- WHEN the PDF document is built twice
- THEN the two PDF files may legitimately differ without being treated as a determinism failure

### Requirement: Bound Figure Label Resolves to an Embedded Image

A symbolic figure label (`[[figure:label]]`) bound to a catalog figure MUST
resolve, at build/assemble time, to an EMBEDDED image in the assembled
output -- not merely to a text caption/number. Embedding MUST be achieved by
emitting Markdown image syntax (`![caption](path){width=...}`) at the
label-resolution hook so the existing pandoc-backed render path embeds the
image natively; no new manual image-insertion mechanism is required. An
UNbound label (no catalog figure bound to it) MUST remain text-only, exactly
as it behaves today, so existing documents that only use text
numbering/cross-references are unaffected.

#### Scenario: Bound label embeds the image

- GIVEN a symbolic figure label bound to a figure present in the figure
  catalog under `assets_dir/figures/`
- WHEN the document is built
- THEN the assembled output contains the embedded image at the label's
  resolved position, alongside its resolved caption and number

#### Scenario: Unbound label stays text-only

- GIVEN a symbolic figure label with no catalog figure bound to it
- WHEN the document is built
- THEN the label resolves to text (caption/number) only, with no image
  embedded, matching prior behavior

#### Scenario: Embedding does not alter numbering/cross-reference resolution

- GIVEN a section containing both a bound figure label and a "Ver {ref}"
  cross-reference to it
- WHEN the document is built
- THEN the figure number and cross-reference resolve exactly as they did
  before this requirement, in addition to the image now being embedded

### Requirement: Graceful Degradation on Missing or Corrupt Bound Image

If a bound figure label's underlying image file is missing or unreadable at
build time, the system MUST degrade to caption-only rendering for that
figure (numbering and cross-references still resolve) and MUST WARN naming
the affected label and file, rather than crashing the assemble stage.

#### Scenario: Missing image file degrades gracefully

- GIVEN a symbolic figure label bound to a catalog entry whose image file
  has been deleted from `assets_dir/figures/` since ingest
- WHEN the document is built
- THEN the build completes, the figure's caption and number still resolve,
  no image is embedded for that figure, and the build output includes a
  WARNING naming the missing file

#### Scenario: Corrupt image file degrades gracefully

- GIVEN a symbolic figure label bound to a catalog entry whose image file is
  present but unreadable/corrupt
- WHEN the document is built
- THEN the build completes without crashing, the figure's caption and
  number still resolve, no image is embedded for that figure, and the build
  output includes a WARNING naming the affected label and file

#### Scenario: One degraded figure does not affect other figures

- GIVEN a document with multiple bound figure labels, one of which has a
  missing image
- WHEN the document is built
- THEN every other bound figure embeds normally, and only the affected
  figure degrades to caption-only

### Requirement: Embedded-Image Build Determinism

The assembled output produced by the embedded-image build path MUST be
byte-identical across independent runs given unchanged section Markdown,
figure catalog, and configuration -- matching the existing determinism
guarantee for non-embedded builds.

#### Scenario: Embedded build is byte-identical across runs

- GIVEN unchanged section Markdown, an unchanged figure catalog, and
  unchanged configuration, with at least one bound figure label
- WHEN the document is built twice independently
- THEN the two output files are byte-identical
