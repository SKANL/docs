# Asset Management Specification

## Purpose

Manage document assets (embedded files, images, media) with configurable kind validation so the harness supports multiple asset types without hardcoded format assumptions.

## Requirements

### Requirement: Asset-Kind Validation

The system MUST validate assets against a configurable asset-kind concept (allowed extensions per kind) instead of a hardcoded ".docx-only" check.

#### Scenario: Accept an allowed asset kind

- GIVEN an asset-kind configuration that allows ".docx" (and any other configured kind)
- WHEN an asset of an allowed kind is added
- THEN it is accepted and stored under the document's assets directory

#### Scenario: Reject a disallowed asset kind

- GIVEN an asset-kind configuration
- WHEN an asset whose type is not in the allowed set is added
- THEN the system raises a clear error naming the rejected file and its type

#### Scenario: DOCX-only configuration behaves as before

- GIVEN an asset-kind configuration that only allows "docx"
- WHEN a non-docx file is added
- THEN it is rejected, preserving prior behavior for documents that only use DOCX assets

### Requirement: Asset Repository Port Generalization

The `AssetRepository` port MUST expose a kind-agnostic listing method (e.g., `list_assets(directory, kind)`) replacing the DOCX-specific `glob_docx`.

#### Scenario: List assets by kind

- GIVEN an assets directory containing files of multiple configured kinds
- WHEN `list_assets` requests a specific kind (e.g., "docx")
- THEN only files matching that kind are returned

#### Scenario: Existing DOCX listing behavior preserved

- GIVEN an assets directory with only `.docx` files
- WHEN assets are listed for kind "docx"
- THEN the result matches what the previous `glob_docx`-based listing returned

### Requirement: Verbatim-Asset Pre-Ingest Routing

The system MUST detect verbatim assets via the `inbox/assets/` folder
convention plus heuristic classification of the likely placement kind, and
MUST route them directly into asset storage as a pre-ingest step, so a
declared verbatim asset never reaches the markdown-flattening ingest
handlers.

#### Scenario: File under inbox/assets/ bypasses markdown ingest

- GIVEN a file placed under `inbox/assets/`
- WHEN the pipeline's ingest stage runs
- THEN the file is routed to asset storage before markdown-flattening
  handlers run
- AND it never appears as a converted markdown source

#### Scenario: Heuristic classifies likely placement kind

- GIVEN a verbatim asset with a filename/content signal (e.g., "cover",
  "portada")
- WHEN pre-ingest routing runs
- THEN the asset is tagged with its heuristically detected likely placement
  kind for the pending-placement queue

### Requirement: Pending-Placement Queue and Placement Manifest

Detected verbatim assets MUST be added to a pending-placement queue for
external confirmation of final placement (cover/front/back); confirmed
placement MUST be recorded in a placement manifest, and unconfirmed assets
MUST NOT receive a default placement.

#### Scenario: Newly detected asset is queued

- GIVEN a newly routed verbatim asset
- WHEN pre-ingest routing completes
- THEN the asset appears in the pending-placement queue with its
  heuristically detected kind

#### Scenario: Confirmed placement is recorded and usable

- GIVEN a queued asset whose placement has been confirmed externally
- WHEN the confirmation is applied
- THEN the placement manifest records the confirmed placement
- AND assembly can reference the asset at its confirmed placement

#### Scenario: Unconfirmed asset is never auto-placed

- GIVEN an asset still pending confirmation
- WHEN assembly runs
- THEN the asset is not placed anywhere automatically
- AND the pipeline reports it as pending, not silently omitted

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
