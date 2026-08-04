# Delta for Document Pipeline

## ADDED Requirements

### Requirement: Generate-Visuals Stage and Ordering

The system MUST provide a `generate-visuals` stage that renders
agent-declared visuals from `sections/visual-specs.json` (per the
document-visuals capability), merges the results into `figure-catalog.json`
(via asset-management's `merge()`) and `figure-bindings.json`, and MUST run
it strictly after the `ingest` stage set (so the base figure catalog exists
to merge into) and strictly before `assemble` (so the resolver used by
`docx_assembly`/`html_render` sees the generated entries). The stage MUST be
format-agnostic (no branching on output format) and MUST WARN+skip on a
per-visual failure rather than failing the whole stage or the pipeline run.

#### Scenario: generate-visuals runs after ingest and before assemble

- GIVEN a document with sources in `inbox/` and a `visual-specs.json`
  declaring one visual
- WHEN the pipeline runs `ingest` then `generate-visuals` then `assemble`
- THEN the visual's catalog entry and binding exist before `assemble` reads
  the figure resolver, and the base ingest-produced catalog entries are
  still present

#### Scenario: generate-visuals is a no-op without visual-specs.json

- GIVEN a document with no `sections/visual-specs.json` file
- WHEN the pipeline runs the `generate-visuals` stage
- THEN it completes successfully having generated nothing, and the rest of
  the pipeline (ingest, assemble) behaves exactly as it did before this
  capability existed

#### Scenario: A per-visual failure warns and the pipeline continues

- GIVEN a `visual-specs.json` entry that fails to render (malformed source
  or missing toolchain)
- WHEN the `generate-visuals` stage runs as part of a full pipeline
  (`all`) execution
- THEN the stage reports success with a WARNING detail naming the skipped
  visual
- AND the `assemble` stage still runs and produces output

#### Scenario: Full pipeline determinism holds with generated visuals

- GIVEN unchanged sources, an unchanged `visual-specs.json`, and the same
  pinned toolchain
- WHEN the full pipeline (`all`) runs twice independently
- THEN the resulting `figure-catalog.json`, `figure-bindings.json`,
  generated SVG/PNG files, and final docx/HTML output are all byte-identical
  across both runs
