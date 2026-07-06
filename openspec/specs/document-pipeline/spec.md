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
