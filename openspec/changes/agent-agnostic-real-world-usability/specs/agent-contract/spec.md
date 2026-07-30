# Agent Contract Specification

## Purpose

Give any code agent (Claude Code, Codex, OpenCode, or other) a single, authoritative, queryable description of how to drive the harness end-to-end over CLI + files, without reading source or tests.

## Requirements

### Requirement: Single-Source Contract Content

The agent contract (workflow steps, config, figure/table conventions, review loop, cognitive-slot boundary) MUST be authored in exactly one source location. Both the shipped `AGENTS.md` file and the `docs guide` command MUST render from that single source, never diverging copies.

#### Scenario: Guide and file agree

- GIVEN the single source content
- WHEN `AGENTS.md` is generated and `docs guide` is invoked
- THEN both present identical guidance content for the same topic

#### Scenario: Source updated once, both surfaces reflect it

- GIVEN the single source is edited
- WHEN `AGENTS.md` is regenerated and `docs guide` is re-run
- THEN both surfaces show the updated content with no manual duplication step missed

### Requirement: Shipped `AGENTS.md`

The system MUST ship an `AGENTS.md` file at the repository/workspace root covering the full workflow: ingest → context → prep → author → review → assemble → verify, plus config, figure/table conventions, and the cognitive-slot boundary between harness and agent.

#### Scenario: Agent reads AGENTS.md only

- GIVEN a fresh agent with only `AGENTS.md` and CLI `--help` output
- WHEN it attempts to generate a document end-to-end
- THEN every required step (ingest, context, prep, author, review, assemble, verify) is documented with the command to run

### Requirement: `docs guide` CLI Command

The system MUST provide a `docs guide` command that prints the agent contract to stdout, so the contract is queryable without filesystem access to `AGENTS.md`.

#### Scenario: Query the guide from the CLI

- GIVEN the `docs` CLI is installed
- WHEN `docs guide` runs
- THEN it prints the full workflow guidance without requiring a repository checkout

### Requirement: Review-Loop and Cognitive-Slot Documentation

The contract MUST document the `review-section --json` iterate-to-green loop and explicitly mark which fields/slots are harness-mechanical versus agent-authored.

#### Scenario: Iterate-to-green loop documented

- GIVEN the agent contract
- WHEN an agent looks up how to resolve review findings
- THEN it finds the `review-section --json` loop documented with expected inputs/outputs

#### Scenario: Cognitive-slot boundary is explicit

- GIVEN the agent contract
- WHEN an agent looks up which content it must author versus what the harness generates
- THEN the boundary is stated unambiguously, matching the mechanical-core/guided-layer split
