# Delta for Asset Management

## MODIFIED Requirements

### Requirement: Deterministic Figure Catalog

The system MUST build a deterministic figure catalog for image/figure
assets, recording content hash, dimensions, origin, source subfolder,
**source role**, and **origin kind** for each figure. `source_role` records
the mechanically classified provenance role of the figure's originating
source (e.g., evidence vs. `guia`/example/reference); `origin_kind` records
whether the entry originated from a standalone declared/heuristic image
file, a rendered PDF page, or a harness-rendered visual declared by the
agent (`generated`, per the document-visuals capability). The catalog is a
deterministic INVENTORY of ingested/generated figure assets. Referencing
figures and resolving their captions/numbers at assembly is owned by the
document-render capability's symbolic-label mechanism (see document-render
"Figure and Table Auto-Numbering"): the catalog records the asset metadata,
and the render layer resolves author-facing references by symbolic label --
there is no separate catalog-identifier reference syntax.
(Previously: `origin_kind` distinguished only `standalone` and
`pdf_render`; `generated` is a new valid value for agent-declared,
harness-rendered visuals.)

#### Scenario: Catalog is byte-identical across runs

- GIVEN the same set of figure assets and configuration
- WHEN the figure catalog is built twice independently
- THEN both catalogs are byte-identical

#### Scenario: Catalog entry records required metadata

- GIVEN a figure asset processed into the catalog
- WHEN its catalog entry is inspected
- THEN it records the content hash, dimensions, origin, source subfolder,
  `source_role`, and `origin_kind`

#### Scenario: Figure references resolve at assembly via the render layer

- GIVEN a section that references a figure by a symbolic label (per the
  document-render capability) and that figure is present in the catalog
- WHEN the document is assembled
- THEN the reference, its caption, and its number resolve correctly through
  the document-render symbolic-label mechanism, while the catalog remains
  the deterministic inventory of the underlying asset

#### Scenario: Catalog entry records origin_kind=generated for a harness-rendered visual

- GIVEN a visual rendered by the document-visuals `generate-visuals` stage
- WHEN its catalog entry is inspected
- THEN `origin_kind` is `"generated"`

## ADDED Requirements

### Requirement: Deterministic Figure-Catalog Merge

The system MUST provide a pure `merge()` helper in
`domain/figure_catalog.py` that combines two sets of figure-catalog entries
by `id` (union, re-sorted by `id`, no duplicate ids, no dropped entries), so
a stage that runs after ingest (e.g. `generate-visuals`) can layer its
entries on top of ingest's catalog without clobbering it. All catalog I/O
(reading the prior catalog, writing the merged result) remains the calling
stage's responsibility, not the pure `merge()` function's.

#### Scenario: Merging generated entries preserves all ingest entries

- GIVEN an existing `figure-catalog.json` produced by ingest, and a set of
  newly generated visual entries
- WHEN `merge()` combines them
- THEN every ingest-produced entry is present in the merged result
- AND every newly generated entry is present in the merged result

#### Scenario: Merged catalog is re-sorted and deterministic

- GIVEN two entry sets to merge
- WHEN `merge()` is called twice with the same two inputs, in either order
- THEN both merge results are byte-identical and sorted by `id`

#### Scenario: Merging is safe to re-run

- GIVEN a `figure-catalog.json` that already contains a given generated
  entry (from a prior `generate-visuals` run)
- WHEN `generate-visuals` re-renders the same visual and merges again
- THEN the entry is not duplicated in the merged catalog
