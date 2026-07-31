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

The pipeline MUST include an `ingest` stage set (format-agnostic like
`prep`) for source conversion, plus context-curation stages for building
skeleton and index files, wired into the composition root without coupling
domain/pipeline code to their implementations. The ingest stage MUST also
apply the asset-management capability's mechanical role/provenance filter to
figure candidates (excluding example/reference-role `guia` images) and copy
surviving candidates to the document's stable `assets_dir/figures/` path, so
later stages (including assemble-time embedding) can reference them without
depending on the ephemeral `inbox/` contents.

#### Scenario: Ingest stage available alongside prep/assemble/all

- GIVEN the pipeline CLI command
- WHEN `--help` is displayed
- THEN ingest is listed as a valid stage option

#### Scenario: Context-curation stages integrate into the pipeline

- GIVEN a full pipeline run with the ingest stage_set
- WHEN execution completes
- THEN ingested sources, context files, and the curated index are all
  present in the document context directory

#### Scenario: Full pipeline determinism end-to-end

- GIVEN the same source inbox and configuration
- WHEN the pipeline runs twice independently
- THEN all ingested Markdown files, context files, and final DOCX output are
  byte-identical across both runs

#### Scenario: Ingest excludes reference-role images and copies survivors deterministically

- GIVEN an inbox containing both an evidence-role standalone image and an
  example/reference-role (`guia`) standalone image
- WHEN the `ingest` stage runs
- THEN the evidence-role image is copied to `assets_dir/figures/` and
  recorded in the figure catalog, the `guia` image is excluded from both the
  catalog and `assets_dir/figures/`, and running ingest twice produces
  byte-identical catalog and `assets_dir/figures/` contents

### Requirement: Reproducibility Boundary Principle

The system MUST treat section Markdown files as the durable source of truth for document content, and the built `.docx`/HTML output as a deterministic function of those Markdown files plus configuration. Byte-for-byte determinism applies to the docx and HTML build steps; it MUST NOT be required of agent-authored prose across independent authoring sessions. PDF output is an explicitly non-byte-deterministic derived artifact (rendered via external toolchains), and MUST NOT be held to the byte-identity guarantee.

#### Scenario: Rebuilding from unchanged sources is byte-identical (docx/HTML)

- GIVEN unchanged section Markdown files and configuration
- WHEN the docx or HTML output is built twice
- THEN the two output files are byte-identical

#### Scenario: Prose changes are not a determinism violation

- GIVEN an agent edits a section's Markdown content between two authoring sessions
- WHEN the document is rebuilt after the edit
- THEN the output legitimately differs, and this is not treated as a determinism failure

#### Scenario: PDF output is not required to be byte-identical

- GIVEN unchanged section Markdown files and configuration
- WHEN the PDF output is built twice
- THEN the two PDF files may legitimately differ, and this is not treated as a determinism failure

#### Scenario: PDF toolchain absent degrades gracefully

- GIVEN neither `soffice` nor a PDF-capable `pandoc` path is available
- WHEN a build requests PDF output
- THEN the system WARNs and skips the PDF artifact, and other requested formats still build successfully

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

### Requirement: Review Reads Rule Data From Template Config

Review logic MUST read citation style, contested-stack terms, subjective/forbidden word lists, and format params from the active document's template config at runtime, rather than from hardcoded module-level constants.

#### Scenario: No hardcoded rule identifiers remain

- GIVEN `domain/rules.py` and `domain/source_role.py` after this change
- WHEN inspected
- THEN they contain no estadia-specific term lists or citation-style literals; all such data is loaded from template config

#### Scenario: Estadia review is byte-identical after the refactor

- GIVEN the estadia template's config (declaring current values) and an unchanged estadia document
- WHEN review runs before and after this refactor
- THEN both produce byte-identical findings

### Requirement: Output-Format Selection

The pipeline/CLI MUST allow selecting `html` and/or `pdf` as target output formats alongside the existing `docx`, resolved through the same format-registry mechanism as `document-render`.

#### Scenario: Select html output

- GIVEN a document config requesting `html` output
- WHEN assemble runs
- THEN an HTML artifact is produced via the format registry

#### Scenario: Select pdf output

- GIVEN a document config requesting `pdf` output
- WHEN assemble runs
- THEN a PDF artifact is produced via the format registry, or a WARN+skip if the PDF toolchain is absent

### Requirement: Template-Declared Review-Rules Checks

`review-rules` checks MUST be driven entirely by what the resolved template
declares — conditional checks that run only when their policy block is
present, and consistency checks that compare a template's declared values
against itself, never against a hardcoded literal.

#### Scenario: APA gate respected

- GIVEN a template with `apa7.enabled` set to `false`
- WHEN `review-rules` runs
- THEN no APA-compliance check is required to pass, and none is forced true

#### Scenario: Preliminaries checked only when declared

- GIVEN a template with a `preliminaries` block declared
- WHEN `review-rules` runs
- THEN the check compares the document against the template's own declared
  structure (e.g., its own body-restart section id), not a fixed literal

#### Scenario: Margins checked for shape, not value

- GIVEN a template declaring a `page_margins_cm` block
- WHEN `review-rules` runs
- THEN it verifies the declared keys hold numeric centimeter values
- AND it does not require any specific numeric value

#### Scenario: Extracted-dir policy checked only when configured

- GIVEN a template with no `paths.extracted_dir` configured
- WHEN `review-rules` runs
- THEN the extracted-dir policy check does not execute
- AND when `paths.extracted_dir` IS configured, the check verifies the
  declared policy string is internally consistent with `source_priority`

### Requirement: Build-Rules Guards Absent Paths

The `build-rules` stage MUST NOT raise an unhandled exception when template
`paths` configuration is empty or missing keys; it MUST skip the affected
sub-step or degrade with a reported gap instead of crashing.

#### Scenario: Empty paths config does not crash build-rules

- GIVEN a template with an empty `paths` object
- WHEN the `build-rules` stage runs
- THEN it completes without raising `KeyError` or any unhandled exception

#### Scenario: Missing path reported as a gap, not a crash

- GIVEN a template missing `paths.manual_dir` or `paths.extracted_dir`
- WHEN `build-rules` runs
- THEN the affected sub-step is skipped or degraded
- AND the missing configuration is reported, not silently ignored

### Requirement: Document Workspace Creation Includes Ingest Inbox

Creating a new document workspace MUST create the source-ingest `inbox/`
directory alongside existing workspace subdirectories, so ingest has a
target directory without manual setup.

#### Scenario: New document workspace includes inbox/

- GIVEN a user creates a new document
- WHEN workspace creation completes
- THEN an empty `inbox/` directory exists under the document's workspace

#### Scenario: Existing workspace creation behavior preserved

- GIVEN a user creates a new document
- WHEN workspace creation completes
- THEN all previously created subdirectories (e.g., `corrections/`) still exist

### Requirement: Machine-Readable Gap Report

The system MUST produce a machine-readable gap report (`gap-report.json`)
combining context required-field gaps and section `required_content` gaps.
In draft mode the pipeline MUST proceed, marking gaps with `PENDIENTE`
markers; in strict mode the pipeline MUST block on any reported gap. This
report is the machine-readable data source that the document-ingest
capability's human/agent-readable Intake Report renders over — it underlies,
and is not superseded by, that readable surface.

#### Scenario: Draft mode proceeds with PENDIENTE markers

- GIVEN required context fields or section content are missing
- WHEN the pipeline runs in draft mode
- THEN it completes, inserting `PENDIENTE` markers at each gap
- AND the gap report lists every marker's location and cause

#### Scenario: Strict mode blocks on gaps

- GIVEN the same missing fields/content
- WHEN the pipeline runs in strict mode
- THEN it stops before producing final output and surfaces the gap report

#### Scenario: Gap report is structured, not free text

- GIVEN a pipeline run that produced any gaps
- WHEN the gap report is inspected
- THEN it is machine-parseable (e.g., JSON) listing field/section identifiers
