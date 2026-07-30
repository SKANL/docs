# Document Pipeline Specification

## Purpose

The pipeline orchestrates the conversion of a document from authoring, through review, to final publication. It provides composable, format-agnostic stages for prep (audience/context setup), ingest (source conversion), context curation, assembly, and verification. The pipeline must support multiple output formats without touching domain/pipeline code.

## Requirements

### Requirement: Data-Driven, Format-Agnostic Stage Plan

The system MUST derive the ordered list of pipeline stages from configuration/registry keyed by target output format, rather than a single hardcoded stage list. Stage names, ordering, and fail-fast flags MUST contain no format-specific or "tesina" identifiers in the domain layer.

#### Scenario: Unknown stage_set still rejected

- GIVEN a stage_set not in `prep`, `assemble`, `all`, `ingest`
- WHEN `pipeline_stage_plan` is called
- THEN it raises a clear `ValueError` naming the invalid stage_set

#### Scenario: Stage plan resolved per configured format

- GIVEN a config/template specifying output format "docx"
- WHEN the stage plan is requested
- THEN the returned stages match the format-specific configuration in dependency order

#### Scenario: No hardcoded format identifiers remain

- GIVEN the `domain/pipeline.py` module
- WHEN inspected
- THEN it contains no literal "tesina" or DOCX-only sentinel identifiers in stage-plan logic

#### Scenario: Deterministic ordering

- GIVEN the same stage_set and format configuration
- WHEN `pipeline_stage_plan` is called twice
- THEN both calls return an identical, stably ordered list

### Requirement: Repository Port Segregation

The system MUST split the fat `DocumentRepository` port into smaller, cohesive ports (e.g., registry access, document content access, template access) so consumers depend only on the methods they use.

#### Scenario: Consumer depends on a narrow port

- GIVEN a use case that only reads/writes document content
- WHEN it declares its dependency
- THEN it depends on a content-focused port, not the full former `DocumentRepository` surface

### Requirement: CLI Composition Root Segregation

The system MUST split `cli/main.py` into cohesive sub-applications by concern (e.g., pipeline, assets, ingest) and MUST remove the dead root `main.py` entrypoint.

#### Scenario: CLI commands remain reachable after split

- GIVEN the CLI split into sub-apps
- WHEN a user runs any previously existing command
- THEN it behaves identically to before the split

#### Scenario: No dead entrypoint

- GIVEN the repository root
- WHEN inspected after this change
- THEN no unused root `main.py` exists

### Requirement: Dependency Declaration and Error-Handling Correctness

The system MUST declare `docxcompose`, `filetype`, and `opendataloader-pdf` as explicit dependencies in `pyproject.toml`, and MUST NOT silently swallow exceptions in `filesystem_source_repository.py`.

#### Scenario: Dependencies declared

- GIVEN `pyproject.toml`
- WHEN inspected
- THEN `docxcompose`, `filetype`, and `opendataloader-pdf` are declared dependencies

#### Scenario: Git helper failure is surfaced, not swallowed

- GIVEN a git subprocess call in `filesystem_source_repository.py` fails
- WHEN the failure occurs
- THEN it is logged or re-raised with context, not silently caught and hidden

### Requirement: Application-Layer Test Coverage and Index De-duplication

The system MUST have automated unit tests covering application-layer services, and MUST de-duplicate the `_sections_index` logic into a single shared implementation.

#### Scenario: Application services are unit-tested

- GIVEN application-layer services (e.g., pipeline, asset, ingest orchestration)
- WHEN `uv run pytest` runs
- THEN each service has at least one passing unit test exercising its core behavior

#### Scenario: Single `_sections_index` implementation

- GIVEN the codebase after this change
- WHEN searched for `_sections_index` logic
- THEN exactly one implementation exists, reused by all former call sites

### Requirement: Ingest Stage and Context-Curation Integration

The pipeline MUST include an `ingest` stage set (format-agnostic like `prep`) for source conversion, plus context-curation stages for building skeleton and index files, wired into the composition root without coupling domain/pipeline code to their implementations.

#### Scenario: Ingest stage available alongside prep/assemble/all

- GIVEN the pipeline CLI command
- WHEN `--help` is displayed
- THEN ingest is listed as a valid stage option

#### Scenario: Context-curation stages integrate into the pipeline

- GIVEN a full pipeline run with the ingest stage_set
- WHEN execution completes
- THEN ingested sources, context files, and the curated index are all present in the document context directory

#### Scenario: Full pipeline determinism end-to-end

- GIVEN the same source inbox and configuration
- WHEN the pipeline runs twice independently
- THEN all ingested Markdown files, context files, and final DOCX output are byte-identical across both runs

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

### Requirement: Reproducibility Boundary Principle (Item M)

Section Markdown files MUST be treated as the durable source of truth for document content; the built `.docx`/format output MUST be a deterministic function of them + config. Byte-determinism applies to the BUILD, not agent prose across sessions.

#### Scenario: Rebuilding from unchanged sources is byte-identical

- GIVEN unchanged section Markdown files and configuration
- WHEN the document is built (assembled/rendered) twice
- THEN the two output files are byte-identical

#### Scenario: Prose changes are not a determinism violation

- GIVEN an agent edits a section's Markdown content between two authoring sessions
- WHEN the document is rebuilt after the edit
- THEN the output legitimately differs, and this is not treated as a determinism failure
