# Document Render Specification

## Purpose

Provide a `DocumentRendererPort` abstraction resolved by target output format, with DOCX as the only concrete adapter today, and prove the port is genuinely extensible to other formats without touching domain/pipeline code.

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
