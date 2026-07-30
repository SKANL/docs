# Delta for Document Pipeline

## ADDED Requirements

### Requirement: Fail-Open Doctor for Optional Inputs

`doctor` MUST WARN, not hard-fail, when an optional input (e.g., a manual) is missing, and MUST auto-detect optional inputs like the manual anywhere under the inbox by content rather than a hardcoded path. The document generation MUST still proceed with clearly-marked gaps when only optional inputs are missing. A `--strict` flag MUST restore hard-fail behavior for agents/CI that require it.

#### Scenario: Missing optional manual warns, does not fail

- GIVEN an inbox with no manual-like source anywhere
- WHEN `doctor` runs without `--strict`
- THEN it reports a WARNING naming the missing manual and actionable next steps
- AND the overall doctor result is not a failure

#### Scenario: Manual detected anywhere under inbox

- GIVEN a manual-like source placed at an arbitrary path under the inbox (not the previous hardcoded location)
- WHEN `doctor` runs
- THEN it is detected by content and no warning is raised for it

#### Scenario: Strict mode restores hard-fail

- GIVEN an inbox with no manual-like source
- WHEN `doctor --strict` runs
- THEN it fails, matching the previous hard-fail behavior

#### Scenario: Missing required input still fails

- GIVEN an inbox missing an input still marked required (not optional)
- WHEN `doctor` runs, strict or not
- THEN it fails, naming the missing required input

### Requirement: `doc status` Resumable Summary

The system MUST provide a `doc status` command reporting, for the active document: whether context is filled, how many sections are authored vs. scaffolded, which sections need review, whether ingest has run, and whether assemble has run — so an agent can resume work without re-deriving state by hand.

#### Scenario: Fresh document status

- GIVEN a newly created document with no context filled and no sections authored
- WHEN `doc status` runs
- THEN it reports zero filled context fields, 0/N sections authored, ingest not run, assemble not run

#### Scenario: Partially completed document status

- GIVEN a document with context filled, some sections authored and reviewed, ingest run, assemble not run
- WHEN `doc status` runs
- THEN it reports accurate counts and states matching the document's actual filesystem state

### Requirement: Toolchain Validation with Degradable Optional Capabilities

`doctor` MUST validate the required toolchain (uv, pandoc) as hard requirements, and MUST declare figure-rendering dependencies (opendataloader/java; optional mermaid/Chrome/node, pypdfium2/pillow) as OPTIONAL, degradable capabilities that WARN with guidance when absent rather than blocking the pipeline.

#### Scenario: Required toolchain missing fails

- GIVEN `pandoc` is not resolvable
- WHEN `doctor` runs
- THEN it fails, naming `pandoc` as a missing required tool

#### Scenario: Optional render toolchain missing warns only

- GIVEN `pypdfium2`/`pillow` are not installed
- WHEN `doctor` runs
- THEN it WARNs that page-render figure extraction is degraded, with install guidance
- AND does not fail the doctor run for this reason alone

### Requirement: Reproducibility Boundary Principle

The system MUST treat section Markdown files as the durable source of truth for document content, and the built `.docx` (or other rendered format) as a deterministic function of those Markdown files plus configuration. Byte-for-byte determinism applies to the build step; it MUST NOT be required of agent-authored prose across independent authoring sessions.

#### Scenario: Rebuilding from unchanged sources is byte-identical

- GIVEN unchanged section Markdown files and configuration
- WHEN the document is built (assembled/rendered) twice
- THEN the two output files are byte-identical

#### Scenario: Prose changes are not a determinism violation

- GIVEN an agent edits a section's Markdown content between two authoring sessions
- WHEN the document is rebuilt after the edit
- THEN the output legitimately differs, and this is not treated as a determinism failure
