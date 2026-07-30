# Delta for Agent Contract

## ADDED Requirements

### Requirement: Clean-Room Verification Drives AGENTS.md Refinement

The verify phase MUST include a clean-room run — an agent given only the
shipped `AGENTS.md` and arbitrary raw source files, with no access to
harness source code or tests — attempting the full workflow end-to-end. Any
step where the clean-room agent gets stuck for lack of documentation MUST be
treated as a gap and MUST be closed by refining `AGENTS.md`.

#### Scenario: Clean-room agent completes the full workflow
- GIVEN a clean-room agent with only `AGENTS.md` and raw input files
- WHEN it attempts ingest → context → prep → author → review → assemble →
  verify
- THEN it completes every step using only documented commands

#### Scenario: A documentation gap is found and closed
- GIVEN the clean-room agent gets stuck at a step not covered by
  `AGENTS.md`
- WHEN the gap is identified
- THEN `AGENTS.md` is updated to cover it
- AND a subsequent clean-room run no longer gets stuck at that step

## MODIFIED Requirements

### Requirement: Shipped `AGENTS.md`

The system MUST ship an `AGENTS.md` file at the repository/workspace root
covering the full workflow: ingest → context → prep → author → review →
assemble → verify, plus config, figure/table conventions, and the
cognitive-slot boundary between harness and agent. It MUST also document the
`doc revise` semantic-edit loop, output-format selection (docx/html/pdf)
including the PDF non-determinism/graceful-degradation caveat, and the
lifecycle/build-version fields surfaced by `doc status`.
(Previously: covered only the original seven-stage workflow, config,
figure/table conventions, and cognitive-slot boundary — no revise loop,
multi-format selection, or lifecycle coverage.)

#### Scenario: Agent reads AGENTS.md only
- GIVEN a fresh agent with only `AGENTS.md` and CLI `--help` output
- WHEN it attempts to generate a document end-to-end
- THEN every required step (ingest, context, prep, author, review,
  assemble, verify) is documented with the command to run

#### Scenario: Revise loop and format selection documented
- GIVEN the agent contract
- WHEN an agent looks up how to semantically edit a section or select an
  output format
- THEN it finds `doc revise` and format-selection (including the PDF
  non-determinism caveat) documented with example commands
