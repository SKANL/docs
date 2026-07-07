# Delta for Document Ingest

## ADDED Requirements

### Requirement: Recursive Inbox Scan with Provenance

Ingest MUST recursively walk every subfolder of the inbox, capturing each
source file's relative path as provenance metadata in both the detection
report and the source manifest. Ignored or unsupported items, including
files in nested subfolders, MUST always be reported and never silently
skipped.

#### Scenario: Nested subfolder file is detected with provenance

- GIVEN a source file two levels deep under `inbox/`
- WHEN ingest runs
- THEN the file is detected and converted
- AND its relative path is recorded as provenance in the detection report
  and the source manifest

#### Scenario: Unsupported nested file is reported, not silent

- GIVEN an unsupported file type nested inside a subfolder
- WHEN ingest runs
- THEN the file is not crashed on
- AND it appears in the detection report as unsupported, with its path

#### Scenario: Empty subfolder produces no error

- GIVEN an inbox subfolder containing no files
- WHEN ingest runs
- THEN the run completes without error and without phantom report entries

### Requirement: Source-Role Classification

Each ingested source MUST be classified as `normative`, `example`, or
`evidence` using deterministic signals. Ambiguous cases MUST be placed in a
pending-classification queue for external confirmation rather than defaulted
silently. The confirmed role MUST be recorded in the source manifest and
MUST control how downstream stages use that source.

#### Scenario: Deterministic signal classifies unambiguously

- GIVEN a source whose relative path/folder name matches a known role signal
- WHEN ingest runs
- THEN the source manifest records the matched role without human input

#### Scenario: Ambiguous source is queued, not defaulted

- GIVEN a source with no clear role signal
- WHEN ingest runs
- THEN it is added to the pending-classification queue
- AND it is not assigned any role until externally confirmed

#### Scenario: Confirmed role recorded and enforced

- GIVEN a queued source whose role has been confirmed externally
- WHEN the confirmation is applied
- THEN the source manifest records the confirmed role
- AND downstream stages honor that role (e.g., `evidence` sources are
  excluded from normative checks)

### Requirement: Near-Duplicate Detection

The system MUST detect near-duplicate sources via deterministic normalized-
content similarity, prefer the highest-fidelity variant, and record the
decision — which was kept, which suppressed, and why — in the manifest so
it is auditable and reversible.

#### Scenario: Higher-fidelity duplicate is kept

- GIVEN two sources with near-identical normalized content but different
  fidelity (e.g., a PDF-extracted copy and a native DOCX copy)
- WHEN ingest runs
- THEN the higher-fidelity source is kept active
- AND the manifest records the suppressed source and the reason

#### Scenario: Duplicate decision is reversible

- GIVEN a recorded near-duplicate decision in the manifest
- WHEN the manifest entry is edited to reverse the decision
- THEN the previously suppressed source becomes active on the next run

#### Scenario: Distinct sources are not falsely merged

- GIVEN two genuinely distinct sources with unrelated content
- WHEN ingest runs
- THEN neither is flagged as a duplicate of the other

### Requirement: Detection Report Run-vs-Prior Semantics

`_detection.json` MUST distinguish files converted during the current run
(including JVM look-ahead batch siblings converted together) from files
already present from a prior run.

#### Scenario: Batch sibling marked as converted-this-run

- GIVEN two PDF siblings batched together by the look-ahead converter on
  their first run
- WHEN `_detection.json` is written
- THEN both are marked as converted in the current run, not as pre-existing

#### Scenario: Prior-run file marked as already-present

- GIVEN a source already converted in an earlier run
- WHEN ingest runs again with no changes
- THEN `_detection.json` marks it as already-present from a prior run

### Requirement: Orphan Media Directory Cleanup

The system MUST detect and remove orphaned `_media/` directories left behind
when a source is re-ingested, renamed, or removed, without deleting media
still referenced by a current source.

#### Scenario: Re-ingesting a source removes its stale media directory

- GIVEN a source previously ingested with an associated `_media/` directory
- WHEN it is re-ingested and no longer produces that directory
- THEN the stale `_media/` directory is removed

#### Scenario: Referenced media is never deleted

- GIVEN a `_media/` directory still referenced by a current source
- WHEN orphan cleanup runs
- THEN that directory is preserved
