# Delta for Document Pipeline

## ADDED Requirements

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

> Clarification (fresh-context verify, PR1 fix batch, WARNING-3): this
> scenario's last line is satisfied by TWO independent, gated check
> functions in `domain/rules.py`, per design.md's Decision 1a table --
> `_check_extracted_dir_policy` (validates that `paths.extracted_dir_policy`
> is declared as a non-empty string when `paths.extracted_dir` is set) and
> `_check_source_priority_excludes_extracted` (validates `source_priority`
> does not include the template's own declared `paths.extracted_dir` value).
> Neither check cross-references the other's field; design.md is the
> authoritative decision record for the exact split.

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

### Requirement: Machine-Readable Gap Report

The system MUST produce a machine-readable gap report combining context
required-field gaps and section `required_content` gaps. In draft mode the
pipeline MUST proceed, marking gaps with `PENDIENTE` markers; in strict mode
the pipeline MUST block on any reported gap.

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
