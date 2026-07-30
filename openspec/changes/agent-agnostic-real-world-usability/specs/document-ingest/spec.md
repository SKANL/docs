# Delta for Document Ingest

## ADDED Requirements

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
