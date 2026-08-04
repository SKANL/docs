# Document Visuals Specification

## Purpose

Let an agent DECLARE a visual (a Mermaid diagram or a data chart) as intent
in `sections/visual-specs.json`, and have the harness render, normalize,
catalog, and auto-bind it deterministically — so it flows through the
existing `[[figure:label]]` figure-embedding pipeline (asset-management,
document-render) with zero new embed syntax. The renderer contract is
extensible: adding a third visual type (e.g. PlantUML, graphviz) requires
only a new adapter registered against `VisualRendererPort`, no stage or
resolver change.

## Requirements

### Requirement: Extensible Visual-Renderer Registry

The system MUST expose a `VisualRendererPort` with a defined contract, and
MUST resolve the concrete renderer from a visual spec's `type` field via a
`type`-keyed registry constructed at the composition root (mirroring
`ingest_handlers` keyed by `kind`). Domain/pipeline code MUST NOT branch on
visual type.

#### Scenario: Registered type resolves to its renderer

- GIVEN a `visual-specs.json` entry with `type: "mermaid"` and a registered
  Mermaid renderer
- WHEN the `generate-visuals` stage processes the entry
- THEN the Mermaid renderer is selected via the registry to render it

#### Scenario: Unregistered type is rejected without crashing the stage

- GIVEN a `visual-specs.json` entry whose `type` has no registered renderer
- WHEN the `generate-visuals` stage processes the entry
- THEN that entry is WARNed and skipped, naming the unrecognized `type`
- AND other entries in the same file still process

#### Scenario: A third renderer requires no stage/resolver change

- GIVEN a test-only fake renderer registered for a new visual `type`
- WHEN a `visual-specs.json` entry of that `type` is processed
- THEN it renders successfully through the fake
- AND no changes to the `generate-visuals` stage or the figure resolver were
  required to support it

### Requirement: Agent-Authored Visual-Spec Declaration

The system MUST read agent-authored visual declarations from
`sections/visual-specs.json`, a list of entries each shaped
`{label, type, source, caption}`. Absence of this file MUST be a no-op for
the `generate-visuals` stage — the rest of the pipeline behaves exactly as
it did before this capability existed.

#### Scenario: Well-formed entry is processed

- GIVEN a `visual-specs.json` entry with a `label`, a registered `type`, a
  `source`, and a `caption`
- WHEN the `generate-visuals` stage runs
- THEN the entry is rendered, cataloged, and bound

#### Scenario: Missing visual-specs.json is a no-op

- GIVEN a document with no `sections/visual-specs.json` file
- WHEN the `generate-visuals` stage runs
- THEN it completes successfully having generated nothing
- AND the figure catalog and bindings are left exactly as ingest produced
  them

#### Scenario: Malformed entry warns and is skipped, others still process

- GIVEN a `visual-specs.json` list containing one entry missing a required
  field (e.g. no `source`) and one well-formed entry
- WHEN the `generate-visuals` stage runs
- THEN the malformed entry is WARNed and skipped, naming the missing field
- AND the well-formed entry is still rendered, cataloged, and bound

### Requirement: Deterministic SVG and Rasterized PNG per Visual

Each successfully rendered visual MUST produce two sibling artifacts under
`assets_dir/figures/` sharing the same stem: a normalized SVG (for HTML) and
a rasterized PNG (for docx, since pandoc cannot reliably embed SVG in
docx — jgm/pandoc#9195). Given the same visual-spec source, renderer
version, and toolchain, repeated generation MUST produce byte-identical SVG
and byte-identical PNG bytes. Cross-environment byte-identity (differing
`resvg`/font installs) is explicitly NOT guaranteed — determinism holds
same-machine, same-pinned-toolchain.

#### Scenario: Mermaid entry produces sibling SVG and PNG

- GIVEN a well-formed `mermaid`-type visual-spec entry
- WHEN it is rendered
- THEN a normalized SVG and a rasterized PNG, sharing the same stem, exist
  under `assets_dir/figures/`

#### Scenario: Chart entry produces sibling SVG and PNG without a Node/Chrome toolchain

- GIVEN a well-formed `chart`-type visual-spec entry
- WHEN it is rendered
- THEN a normalized SVG and a rasterized PNG, sharing the same stem, exist
  under `assets_dir/figures/`
- AND no Node.js or Chrome/Chromium toolchain was required

#### Scenario: Repeated generation is byte-identical

- GIVEN the same visual-spec source, unchanged configuration, and the same
  pinned toolchain
- WHEN the same visual is generated twice independently
- THEN the resulting SVG bytes are identical across both runs
- AND the resulting PNG bytes are identical across both runs

### Requirement: Catalog Registration and Auto-Bind

Every successfully rendered visual MUST be registered in
`figure-catalog.json` with `origin_kind="generated"`, using the rasterized
PNG's pixel dimensions and file as `origin_relative_path` (per
asset-management's catalog contract). The harness MUST then write the
visual's `label` to the new entry's `fig-<sha8>` id into
`figure-bindings.json`, WITHOUT clobbering any pre-existing binding for that
label — the agent cannot predict the content-hash-derived catalog id ahead
of generation, so the harness (not the agent) owns this bind step.

#### Scenario: Generated visual appears in the catalog as origin_kind=generated

- GIVEN a successfully rendered visual-spec entry
- WHEN the `generate-visuals` stage completes
- THEN `figure-catalog.json` contains an entry for it with
  `origin_kind="generated"` and non-null `width_px`/`height_px` taken from
  the rasterized PNG

#### Scenario: Generated visual is auto-bound to its label

- GIVEN a successfully rendered visual-spec entry with `label: "arch-diagram"`
- WHEN the `generate-visuals` stage completes
- THEN `figure-bindings.json` maps `"arch-diagram"` to the entry's
  `fig-<sha8>` catalog id
- AND a section referencing `[[figure:arch-diagram]]` resolves to an
  embedded image via the existing figure-binding resolution path, with no
  new embed syntax

#### Scenario: Auto-bind never overwrites an existing manual binding

- GIVEN `figure-bindings.json` already maps `label: "arch-diagram"` to a
  manually bound catalog id
- WHEN `generate-visuals` renders a new visual-spec entry that also declares
  `label: "arch-diagram"`
- THEN the pre-existing manual binding for that label is left unchanged
- AND the stage WARNs naming the label collision rather than silently
  overwriting it

### Requirement: Graceful Degradation on Missing Toolchain or Failed Visual

A missing renderer toolchain (e.g. no `resvg`, no Mermaid-capable renderer
on PATH) or a single visual-spec entry that fails to render MUST WARN and
skip only that visual; the `generate-visuals` stage and the overall build
MUST NOT crash or fail because of it.

#### Scenario: Missing renderer toolchain warns and skips affected visuals

- GIVEN the toolchain required by a registered visual type (e.g. `resvg`)
  is absent from the environment
- WHEN `generate-visuals` processes an entry of that type
- THEN that entry is WARNed and skipped, naming the missing toolchain and
  install guidance
- AND entries of other, available types still render successfully

#### Scenario: One failing visual entry does not block the others

- GIVEN a `visual-specs.json` list where one entry's source fails to render
  (e.g. invalid Mermaid syntax) and other entries are well-formed
- WHEN `generate-visuals` runs
- THEN the failing entry is WARNed and skipped, naming the cause
- AND every other entry still renders, catalogs, and binds successfully

#### Scenario: generate-visuals never fails the whole pipeline for a single bad visual

- GIVEN a pipeline run where one visual-spec entry is malformed or
  unrenderable
- WHEN the full pipeline (`all`) runs
- THEN the `generate-visuals` stage reports success with a WARNING detail
  for the skipped entry
- AND subsequent stages (assemble) still run
