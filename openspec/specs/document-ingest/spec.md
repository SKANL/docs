# Document Ingest Specification

## Purpose

Convert arbitrary source documents (PDF, DOCX, ODT, Markdown, TXT) into deterministic Markdown source files via type detection and routing, so any document type can enter the harness pipeline without hardcoded assumptions.

Implemented by `IngestService` over the `SourceIngestPort`, `SourceTypeDetectorPort` and `ContentProbePort` ports, with output identity owned by `ingest_naming` and writes made atomic by `atomic_ingest_write`.

## Requirements

### Requirement: File-Type Detection

The system MUST detect the type of each source file using the `filetype` library (magic-byte sniffing), falling back to file extension when magic-byte detection is inconclusive (e.g., plain text, Markdown).

#### Scenario: Detect binary format by magic bytes

- GIVEN a `.pdf` or `.docx` file in the inbox
- WHEN detection runs
- THEN the system identifies the correct type from its magic bytes

#### Scenario: Fallback to extension for text formats

- GIVEN a `.md` or `.txt` file with no distinguishing magic bytes
- WHEN detection runs
- THEN the system falls back to extension matching and identifies the type correctly

#### Scenario: Unknown or unsupported type

- GIVEN a file whose type cannot be resolved by magic bytes or extension
- WHEN ingest runs
- THEN the system MUST NOT crash or raise an unhandled exception
- AND it MUST produce a clear report entry naming the file as unsupported

### Requirement: Type-Based Ingest Routing

The system MUST route each detected file to its matching ingest handler: PDF to `opendataloader-pdf`, DOCX/ODT to pandoc with `--extract-media`, and Markdown/TXT to frontmatter normalization.

#### Scenario: PDF routed to opendataloader-pdf

- GIVEN a detected PDF source
- WHEN ingest routes it
- THEN `opendataloader-pdf` conversion runs and produces Markdown output

#### Scenario: DOCX/ODT routed to pandoc with media extraction

- GIVEN a detected DOCX or ODT source
- WHEN ingest routes it
- THEN pandoc runs with `--extract-media`, writing Markdown plus a per-document media directory

#### Scenario: Markdown/TXT normalized

- GIVEN a detected Markdown or TXT source
- WHEN ingest routes it
- THEN the system normalizes frontmatter and produces conformant Markdown output

### Requirement: Deterministic and Idempotent Ingest

Given the same input files and configuration, the system MUST produce byte-identical Markdown output across repeated runs, and re-running ingest over an already-processed inbox MUST be safe.

#### Scenario: Repeated run produces identical output

- GIVEN a source file already ingested once
- WHEN ingest runs again on the same input with no changes
- THEN the produced Markdown file is byte-identical to the previous run

#### Scenario: Re-run over partially processed inbox

- GIVEN an inbox where some files were already ingested and others were not
- WHEN ingest runs again
- THEN previously ingested files are not duplicated or corrupted
- AND only unprocessed files are converted

#### Scenario: Empty inbox

- GIVEN an inbox directory with no source files
- WHEN ingest runs
- THEN the system completes without error
- AND reports zero files processed

### Requirement: Tool-Failure Reporting

The system MUST report actionable, non-crashing errors when required external tools are missing or fail, following the existing fail-fast stage-callable pattern.

#### Scenario: Missing pandoc executable

- GIVEN pandoc is not installed or not resolvable via `ToolResolverPort`
- WHEN a DOCX/ODT source is ingested
- THEN the system reports a clear "pandoc not found" error
- AND leaves no partial or corrupt output files

#### Scenario: opendataloader-pdf conversion failure

- GIVEN `opendataloader-pdf` raises an error while converting a PDF
- WHEN ingest processes that file
- THEN the system reports the failure for that file with its cause
- AND applies the configured fail-fast behavior for the stage

### Requirement: Content-Based Source Classification with Confidence Threshold

The system MUST classify each ingested source's role (e.g., manual, reference, requirements) using deterministic content heuristics (file type/extension, PDF title/headings, keyword signals in the first N bytes), not folder-name lexicon alone. Classification MUST report a confidence level. High-confidence classifications MUST be acted on automatically. Low-confidence classifications MUST NOT be silently guessed or auto-routed; they MUST be held in a classification queue file (`inbox/_classification-queue.json`) for explicit confirmation.

#### Scenario: High-confidence classification acts automatically

- GIVEN a source file whose content strongly matches a known role's signals
- WHEN classification runs
- THEN the file is routed to that role automatically with no queuing

#### Scenario: Low-confidence classification is held, not guessed

- GIVEN a source file whose content signals are ambiguous or weak
- WHEN classification runs
- THEN the file is NOT assigned a role automatically
- AND it is written into `inbox/_classification-queue.json` for confirmation
- AND ingest completes without crashing

#### Scenario: Flat arbitrary dump with mixed confidence

- GIVEN an inbox of arbitrarily named files with no role-indicating folder structure
- WHEN classification runs
- THEN files with strong content signals are routed correctly
- AND files with weak signals are queued, never misrouted

### Requirement: Vector-PDF Figure Extraction via Render Adapter

When a PDF source yields zero raster images from the primary ingest path (`opendataloader-pdf`), the system MUST attempt page-render-based figure extraction via the render adapter and add the resulting figures to the figure catalog. If the render toolchain is unavailable, the system MUST degrade cleanly (skip figure extraction, report why) without failing ingest.

#### Scenario: Vector-only PDF gains figures automatically

- GIVEN a vector-only PDF source producing zero raster images via `opendataloader-pdf`
- AND the render toolchain is available
- WHEN ingest processes that file
- THEN page-rendered figures are added to `sections/figure-catalog.json`

#### Scenario: Render toolchain absent

- GIVEN the render toolchain is not available
- WHEN a vector-only PDF is ingested
- THEN ingest completes without failing
- AND the intake report notes figure extraction was skipped and why

### Requirement: Human/Agent-Readable Intake Report

The system MUST produce a single, readable intake report per ingest run summarizing what was found, what is missing, and how to finish — replacing reliance on raw `gap-report.json`/ledger PENDIENTE markers as the primary readable output.

#### Scenario: Intake report generated after ingest

- GIVEN an ingest run over a mixed inbox
- WHEN ingest completes
- THEN an intake report file exists listing found sources, classification queue entries, and any skipped/degraded steps with next-step guidance

### Requirement: Cross-Source Conflict Detection

The system MUST detect conflicting facts across ingested sources (e.g., one source stating a different tech stack than another) using deterministic comparison of extracted facts, and MUST surface each conflict as a WARNING in the intake report/fact ledger rather than silently picking one source.

#### Scenario: Conflicting facts across two sources

- GIVEN two ingested sources asserting different values for the same fact
- WHEN ingest completes
- THEN the intake report/fact ledger lists the conflict as a WARNING naming both sources and values

#### Scenario: No conflicts present

- GIVEN ingested sources with no overlapping conflicting facts
- WHEN ingest completes
- THEN no conflict warnings are emitted

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
