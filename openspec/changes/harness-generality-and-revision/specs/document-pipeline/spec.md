# Delta for Document Pipeline

## ADDED Requirements

### Requirement: Review Reads Rule Data From Template Config

Review logic MUST read citation style, contested-stack terms,
subjective/forbidden word lists, and format params from the active
document's template config at runtime, rather than from hardcoded
module-level constants.

#### Scenario: No hardcoded rule identifiers remain
- GIVEN `domain/rules.py` and `domain/source_role.py` after this change
- WHEN inspected
- THEN they contain no estadia-specific term lists or citation-style
  literals; all such data is loaded from template config

#### Scenario: Estadia review is byte-identical after the refactor
- GIVEN the estadia template's config (declaring current values) and an
  unchanged estadia document
- WHEN review runs before and after this refactor
- THEN both produce byte-identical findings

### Requirement: Output-Format Selection

The pipeline/CLI MUST allow selecting `html` and/or `pdf` as target output
formats alongside the existing `docx`, resolved through the same
format-registry mechanism as `document-render`.

#### Scenario: Select html output
- GIVEN a document config requesting `html` output
- WHEN assemble runs
- THEN an HTML artifact is produced via the format registry

#### Scenario: Select pdf output
- GIVEN a document config requesting `pdf` output
- WHEN assemble runs
- THEN a PDF artifact is produced via the format registry, or a WARN+skip
  if the PDF toolchain is absent

## MODIFIED Requirements

### Requirement: Reproducibility Boundary Principle

The system MUST treat section Markdown files as the durable source of truth
for document content, and the built `.docx`/HTML output as a deterministic
function of those Markdown files plus configuration. Byte-for-byte
determinism applies to the docx and HTML build steps; it MUST NOT be
required of agent-authored prose across independent authoring sessions.
PDF output is an explicitly non-byte-deterministic derived artifact
(rendered via external toolchains), and MUST NOT be held to the
byte-identity guarantee.
(Previously: determinism guarantee covered only docx/generic "rendered
format"; PDF was not distinguished as a non-deterministic exception.)

#### Scenario: Rebuilding from unchanged sources is byte-identical (docx/HTML)
- GIVEN unchanged section Markdown files and configuration
- WHEN the docx or HTML output is built twice
- THEN the two output files are byte-identical

#### Scenario: Prose changes are not a determinism violation
- GIVEN an agent edits a section's Markdown content between two authoring
  sessions
- WHEN the document is rebuilt after the edit
- THEN the output legitimately differs, and this is not treated as a
  determinism failure

#### Scenario: PDF output is not required to be byte-identical
- GIVEN unchanged section Markdown files and configuration
- WHEN the PDF output is built twice
- THEN the two PDF files may legitimately differ, and this is not treated
  as a determinism failure

#### Scenario: PDF toolchain absent degrades gracefully
- GIVEN neither `soffice` nor a PDF-capable `pandoc` path is available
- WHEN a build requests PDF output
- THEN the system WARNs and skips the PDF artifact, and other requested
  formats still build successfully
