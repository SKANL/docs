# Context Curation Specification

## Purpose

Generate small, single-purpose context files (keywords, tone, structure, writing style, formatting rules) as structured, deterministic slots with instructions, plus one progressive-disclosure index. The harness performs all mechanical generation; the agent fills cognitive fields afterward, in a separate auditable step.

## Requirements

### Requirement: Structured Slot Generation

The system MUST generate one Markdown file per context concern, each containing a deterministic skeleton (headings and instructions) with cognitive fields explicitly marked as empty placeholders for the agent to fill.

#### Scenario: Generate a context file skeleton

- GIVEN ingested Markdown sources for a document
- WHEN context-curation runs
- THEN a context file (e.g., `tone.md`) is created with instructions and an explicitly marked empty field for agent content

#### Scenario: Skeleton regeneration preserves agent content

- GIVEN a context file that already contains agent-authored content in its cognitive field
- WHEN context-curation runs again with the same inputs
- THEN the system MUST NOT overwrite or discard the existing agent-authored content

### Requirement: Single Progressive-Disclosure Index

The system MUST produce exactly one index Markdown file following a 3-level progressive-disclosure structure: overview, per-file summary, and pointers to full detail.

#### Scenario: Index lists all generated context files

- GIVEN N generated context files
- WHEN the index is built
- THEN the index contains a level-1 overview and one summary entry per context file
- AND each entry links to its corresponding context file

#### Scenario: Exactly one index file exists

- GIVEN a context-curation run for a document
- WHEN generation completes
- THEN exactly one index file exists for that document (no duplicates, no per-concern indexes)

### Requirement: Auditable Harness/Agent Boundary

Each context file MUST clearly distinguish harness-authored structure/instructions from agent-authored content, and the harness MUST NOT invoke the agent automatically.

#### Scenario: Inspect boundary markers

- GIVEN a generated context file
- WHEN a reviewer inspects it
- THEN harness-authored instructions and agent-authored content are visually and structurally distinguishable

#### Scenario: No automatic agent invocation

- GIVEN context-curation completes
- WHEN the pipeline finishes the mechanical step
- THEN no agent process is triggered automatically; filling cognitive fields remains a separate, explicit step

### Requirement: Deterministic Context-File Set

Given the same ingested sources and context-curation configuration, the system MUST generate the same set of context file names and skeleton structure across repeated runs.

#### Scenario: Same inputs produce same file set

- GIVEN identical ingested sources and configuration
- WHEN context-curation runs twice independently
- THEN both runs produce the same file names and the same skeleton structure per file
