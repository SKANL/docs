# Document Lifecycle Specification

## Purpose

Track a document's lifecycle state (draft/final) and build version across
assemble runs, surfaced through `doc status`, so agents and humans can tell
how far along and how many times a document has been built.

Implemented by the `DocumentStatus` model in `document_status`, aggregated on read by `StatusService` and surfaced through the `doc_status` and `doc_mark_final` commands.

## Requirements

### Requirement: Lifecycle State Recorded on Assemble

Every `assemble` run MUST record the document's current lifecycle state
(`draft` by default, or `final` when explicitly marked) alongside the build
output.

#### Scenario: Fresh document assembles as draft
- GIVEN a document never marked final
- WHEN `assemble` runs
- THEN the recorded lifecycle state is `draft`

#### Scenario: Marked-final document assembles as final
- GIVEN a document explicitly marked `final`
- WHEN `assemble` runs
- THEN the recorded lifecycle state is `final`

### Requirement: Monotonic Build Version

Every `assemble` run MUST record a build version number that increases
monotonically for that document, independent of lifecycle state.

#### Scenario: First assemble starts at version 1
- GIVEN a document assembled for the first time
- WHEN `assemble` completes
- THEN the recorded build version is `1`

#### Scenario: Repeated assemble increments version
- GIVEN a document already assembled at version N
- WHEN `assemble` runs again
- THEN the recorded build version is `N + 1`

### Requirement: `doc status` Surfaces Lifecycle and Version

`doc status` MUST report the document's current lifecycle state and latest
build version alongside its existing resumable-summary fields.

#### Scenario: Status shows lifecycle and version after a build
- GIVEN a document assembled at least once
- WHEN `doc status` runs
- THEN it reports the current lifecycle state and the latest build version

#### Scenario: Status before any assemble shows no version
- GIVEN a document never assembled
- WHEN `doc status` runs
- THEN it reports lifecycle `draft` and no build version yet
