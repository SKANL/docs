# Document Revise Specification

## Purpose

Provide a `doc revise` semantic-edit loop: the harness computes diffs, scopes
re-validation to affected sections, and records provenance for every content
edit an agent makes after initial authoring — while the agent supplies the
actual prose change.

## Requirements

### Requirement: Revise Diff Output

`doc revise` MUST produce a diff for every edit: the affected section's
Markdown content before and after, plus a one-line summary of the change.

#### Scenario: Section prose edit produces a diff
- GIVEN an authored section and an agent-submitted replacement Markdown body
- WHEN `doc revise` applies the edit
- THEN it returns the section's before/after Markdown and a change summary

#### Scenario: Context-topic edit produces a diff
- GIVEN an agent edits a `context/` topic value used by one or more sections
- WHEN `doc revise` applies the edit
- THEN it returns the topic's before/after value and a change summary

### Requirement: Scoped Re-Validation

`doc revise` MUST re-run review ONLY on sections affected by the edit plus
`review-document`; it MUST NOT re-validate unaffected sections.

#### Scenario: Prose edit re-validates only its own section
- GIVEN a single-section prose edit with no dependents
- WHEN `doc revise` completes
- THEN only that section and `review-document` are re-validated

#### Scenario: Context-topic edit ripples to dependent sections
- GIVEN a context-topic edit referenced by N sections
- WHEN `doc revise` completes
- THEN all N dependent sections plus `review-document` are re-validated
- AND sections not referencing the topic are left untouched

### Requirement: Change Provenance

Every `doc revise` invocation MUST record the request text, the set of
changed sections/topics, and a timestamp, appended to a persistent change
history (never overwritten).

#### Scenario: Provenance recorded on revise
- GIVEN a successful `doc revise` call
- WHEN the change is committed
- THEN a provenance entry with request text, changed-section IDs, and
  timestamp is persisted

#### Scenario: History accumulates across revisions
- GIVEN two prior `doc revise` calls already recorded
- WHEN a third `doc revise` call completes
- THEN all three provenance entries remain readable, in chronological order

### Requirement: Revise Scope Boundary

`doc revise` MUST reject structural changes (adding/removing sections) and
source re-ingest; those remain the existing authoring/ingest flows.
`apply-corrections` remains unchanged (mechanical find/replace, no
diff/provenance).

#### Scenario: Structural edit request is out of scope
- GIVEN a revise request asking to add or remove a section
- WHEN `doc revise` processes it
- THEN it is rejected with an error naming `revise` as unsuited for
  structural changes

#### Scenario: apply-corrections behavior is untouched
- GIVEN an existing `apply-corrections` mechanical find/replace call
- WHEN it runs after this change ships
- THEN it behaves identically to before, with no diff or provenance recorded
