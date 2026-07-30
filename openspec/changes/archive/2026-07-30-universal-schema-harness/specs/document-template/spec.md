# Document Template Specification

## Purpose

Define the template lifecycle (`init`/`validate`) and the universal-schema
contract: every document-type policy decision (citation/APA config,
pagination, margins, normative writing-pattern rules, section contracts) is
declared as template data, never hardcoded in domain code. The harness
validates that declared data is internally consistent and complete before
use; it never compares declared values against hardcoded expected literals,
and it never trusts AI-authored template content blindly.

## Requirements

### Requirement: Template Skeleton Generation

`template init` MUST emit a complete, inline-documented skeleton covering
every recognized policy block (apa7, preliminaries, page margins,
extracted-dir policy, section contracts, context schema, normative
overrides), with inline comments explaining each field's purpose and valid
shape.

#### Scenario: init emits a documented skeleton

- GIVEN a user runs `template init` for a new document type
- WHEN the command completes
- THEN a template file is created containing every recognized policy block
- AND each block carries inline documentation explaining its fields

#### Scenario: Optional blocks ship as documented placeholders

- GIVEN the generated skeleton
- WHEN an optional block (e.g., `preliminaries`, `extracted_dir`) is inspected
- THEN it is present as a commented/placeholder entry explaining when to
  populate it and when to remove it

### Requirement: Template Structural and Completeness Validation

`template validate` MUST verify both structure (types/shape of declared
blocks) and completeness (required fields present for whatever policy the
template declares) before a template may be used by any pipeline stage, and
MUST reject an incomplete or invalid template loudly — non-zero exit and a
structured error naming every missing or invalid field.

#### Scenario: Valid template passes

- GIVEN a template with well-formed, complete declared blocks
- WHEN `template validate` runs
- THEN it exits successfully with no reported errors

#### Scenario: Incomplete template rejected loudly

- GIVEN a template missing a required field for a block it declares
- WHEN `template validate` runs
- THEN it exits non-zero and names the missing field explicitly
- AND no pipeline stage may consume this template until fixed

#### Scenario: Structurally invalid template rejected

- GIVEN a template with a type mismatch (e.g., a margin value that is not
  numeric)
- WHEN `template validate` runs
- THEN it exits non-zero and names the invalid field and expected shape

### Requirement: Universal-Schema Policy Contract

ALL document-type policy MUST be declared as template data. The harness
MUST enforce only the internal consistency of what a template declares and
MUST NOT compare declared values against hardcoded expected literals
anywhere in domain code.

#### Scenario: Two differently-shaped templates both pass on their own terms

- GIVEN two templates with structurally different declared policy (e.g.,
  APA disabled vs. enabled, different margin values)
- WHEN each is validated and reviewed independently
- THEN each passes or fails based only on its own declared data, never on
  another document type's values

#### Scenario: No hardcoded document-type literal in domain code

- GIVEN the domain layer after this change
- WHEN inspected for document-type-specific literals (e.g., a fixed
  normative-source string or a fixed section id)
- THEN none are found in policy-check code paths

### Requirement: Optional-Block Absence Semantics

An absent optional policy block MUST mean the corresponding checks do not
run at all — not a default pass, not a failure.

#### Scenario: Absent preliminaries block skips the preliminaries check

- GIVEN a template with no `preliminaries` block declared
- WHEN `review-rules` runs
- THEN no preliminaries-related check executes and none is reported as
  failed or passed

#### Scenario: Absent extracted-dir config skips the extracted-dir check

- GIVEN a template with no `paths.extracted_dir` configured
- WHEN `review-rules` runs
- THEN the extracted-dir policy check does not execute
