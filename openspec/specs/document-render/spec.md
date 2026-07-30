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
