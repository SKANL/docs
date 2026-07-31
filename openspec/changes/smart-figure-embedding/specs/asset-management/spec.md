# Delta for Asset Management

## MODIFIED Requirements

### Requirement: Deterministic Figure Catalog

The system MUST build a deterministic figure catalog for image/figure
assets, recording content hash, dimensions, origin, source subfolder,
**source role**, and **origin kind** for each figure. `source_role` records
the mechanically classified provenance role of the figure's originating
source (e.g., evidence vs. `guia`/example/reference); `origin_kind` records
whether the entry originated from a standalone declared/heuristic image file
or from a rendered PDF page. The catalog is a deterministic INVENTORY of
ingested figure assets. Referencing figures and resolving their
captions/numbers at assembly is owned by the document-render capability's
symbolic-label mechanism (see document-render "Figure and Table
Auto-Numbering"): the catalog records the asset metadata, and the render
layer resolves author-facing references by symbolic label -- there is no
separate catalog-identifier reference syntax.
(Previously: `FigureEntry` recorded only `sha256`, `width_px`, `height_px`,
and `origin_relative_path`, with no role or origin-kind classification.)

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
  the document-render symbolic-label mechanism, while the catalog remains the
  deterministic inventory of the underlying asset

## ADDED Requirements

### Requirement: Mechanical Role Filter for Figure Candidates

The system MUST exclude example/reference-role (`guia`) figure candidates
from the figure catalog, keeping only evidence-role and user-supplied
candidates. The role filter is mechanical (derived from the mechanically or
human-confirmed classified role of the originating source) and MUST NOT
require or perform agent judgment about a figure's relevance, placement, or
caption -- those remain an unspecified cognitive slot outside this
requirement's scope.

#### Scenario: Example/reference-role image excluded from candidates

- GIVEN a standalone image whose originating source is classified as
  example/reference role (`guia`)
- WHEN the figure catalog is built
- THEN no catalog entry is created for that image

#### Scenario: Evidence-role image kept as a candidate

- GIVEN a standalone image whose originating source is classified as
  evidence role
- WHEN the figure catalog is built
- THEN a catalog entry is created for that image with `source_role` recorded
  as evidence

#### Scenario: User-supplied image kept as a candidate

- GIVEN a standalone image with no example/reference-role classification
  (i.e., not excluded by the mechanical filter)
- WHEN the figure catalog is built
- THEN a catalog entry is created for that image

### Requirement: Stable Asset Path for Surviving Figure Candidates

Figure candidates that survive the mechanical role filter MUST be copied to
a stable location under the document's `assets_dir/figures/` at ingest time,
so later pipeline stages (including assemble-time embedding) can reference
them without depending on the ephemeral `inbox/` contents.

#### Scenario: Surviving candidate exists under assets_dir/figures after ingest

- GIVEN a standalone evidence-role image in `inbox/` that survives the
  mechanical role filter
- WHEN the ingest stage completes
- THEN a copy of that image exists under the document's
  `assets_dir/figures/` directory

#### Scenario: Excluded candidate is not copied

- GIVEN a standalone example/reference-role (`guia`) image in `inbox/`
- WHEN the ingest stage completes
- THEN no copy of that image exists under `assets_dir/figures/`

#### Scenario: Stable-path copy is deterministic

- GIVEN the same set of surviving figure candidates and configuration
- WHEN ingest runs twice independently
- THEN the resulting `assets_dir/figures/` contents are byte-identical
  across both runs
