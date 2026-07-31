# Delta for Document Pipeline

## MODIFIED Requirements

### Requirement: Ingest Stage and Context-Curation Integration

The pipeline MUST include an `ingest` stage set (format-agnostic like
`prep`) for source conversion, plus context-curation stages for building
skeleton and index files, wired into the composition root without coupling
domain/pipeline code to their implementations. The ingest stage MUST also
apply the asset-management capability's mechanical role/provenance filter to
figure candidates (excluding example/reference-role `guia` images) and copy
surviving candidates to the document's stable `assets_dir/figures/` path, so
later stages (including assemble-time embedding) can reference them without
depending on the ephemeral `inbox/` contents.
(Previously: the ingest stage built the figure catalog directly from
`inbox/`-relative paths and vector-rendered PDF pages with no role filter and
no stable-path copy for standalone candidates; only vector-rendered PDF
figures were copied to a stable location.)

#### Scenario: Ingest stage available alongside prep/assemble/all

- GIVEN the pipeline CLI command
- WHEN `--help` is displayed
- THEN ingest is listed as a valid stage option

#### Scenario: Context-curation stages integrate into the pipeline

- GIVEN a full pipeline run with the ingest stage_set
- WHEN execution completes
- THEN ingested sources, context files, and the curated index are all
  present in the document context directory

#### Scenario: Full pipeline determinism end-to-end

- GIVEN the same source inbox and configuration
- WHEN the pipeline runs twice independently
- THEN all ingested Markdown files, context files, and final DOCX output are
  byte-identical across both runs

#### Scenario: Ingest excludes reference-role images and copies survivors deterministically

- GIVEN an inbox containing both an evidence-role standalone image and an
  example/reference-role (`guia`) standalone image
- WHEN the `ingest` stage runs
- THEN the evidence-role image is copied to `assets_dir/figures/` and
  recorded in the figure catalog, the `guia` image is excluded from both the
  catalog and `assets_dir/figures/`, and running ingest twice produces
  byte-identical catalog and `assets_dir/figures/` contents
