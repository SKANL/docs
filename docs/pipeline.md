# Docs Harness v2 Pipeline

Use this page as the operational path. The source stages are explicit commands; build and verify then execute the contract-driven runtime.

## Quick path

```bash
uv run docs doc new report --template technical-report-srs
uv run docs document status --json
uv run docs document ingest --json
uv run docs document prepare --json
# author section Markdown under the document's sections/ directory
uv run docs document build --format docx --policy strict --json
uv run docs document verify --format docx --policy strict --json
uv run docs document inspect documents/report/output/current/report.docx --json
uv run docs document package documents/report/output/current documents/report/output/release/release.zip --json
uv run docs document publish documents/report/output/current/report.docx documents/report/output/release/report.docx --policy release --json
```

`document ingest` converts inbox material. `document prepare` repeats ingest, normalizes ingested Markdown, and writes the compiled source structure. Both commands persist `docs.sources/v2` reports below `runs/`; they do not author section prose.

## Source preparation reports

| Operation | Report | Stage(s) | Main derived files |
|---|---|---|---|
| `document ingest` | `runs/v2-ingest.json` | `ingest-sources` | `sections/ingested/*`, registered assets, ingest report data |
| `document prepare` | `runs/v2-prepare.json` | `ingest-sources`, `normalize-sources`, `compile-structure` | normalized ingested Markdown and `sections/v2-structure.json` |

Each report has `schema: "docs.sources/v2"`, `document_id`, `succeeded`, ordered `stages`, and `artifacts`. This shape is also mandatory for failure reports: construction, invocation, malformed-result, and empty-stage failures retain the selected document's `document_id`. A source command exits non-zero when its report is unsuccessful. Use `document ingest` to convert inbox material and `document prepare` to add normalization and structure compilation; the command tree exposes those boundaries directly.

## Stage results

Build and verify return a runtime report containing `capabilities`, `execution`, `provenance`, and `succeeded`. `execution.results` is ordered and each result contains:

- `stage`: stable stage identifier;
- `ok`: whether the stage is accepted by the active policy;
- `outcome`: `succeeded`, `failed`, `skipped`, or `unsupported`;
- `artifacts`: artifact records emitted by the stage;
- `warnings` and `errors`: visible policy/degradation evidence.

A `failed` stage stops its downstream dependency chain. A visible optional `unsupported` result is not the same as a successful implementation; strict/release publication still fails when a required capability or contract is unavailable. The runtime only records successful run hashes after the complete accepted execution.

## Traceability boundary

`docs/traceability.json` records executable evidence as repository-relative
pytest node IDs in fields named `test`. Run
`uv run python tools/validate_traceability.py` to check the complete file. The
validator recursively finds those fields, rejects empty, duplicate, absolute,
or traversal-shaped references, and asks pytest to collect only the referenced
test files. Parameterized collection IDs are normalized to their base
`file::test` node before comparison.

This is a resolution check, NOT a semantic proof engine. A collected test proves
only what its assertions establish; the validator cannot infer that nearby
prose accurately describes those assertions. Reviewers must read each
referenced test and narrow or remove unsupported claims. The traceability file
therefore groups evidence around the bounded behavior each test asserts rather
than manufacturing one success claim per declared stage.

## Full stage plan

`FULL_STAGE_IDS` is authoritative and ordered as follows. The public boundaries
below are registered as validated sub-DAGs, reuse the same stage handlers, and are selectable with `--pipeline`;
they are not separate format-specific implementations:

```text
source-ingest | document-prepare | document-build | document-verify
| document-publish | document-package | document-diff | document-inspect
```

`source-ingest` through `document-package` are **stage-backed public
pipelines**: each selects a non-empty stage sub-DAG from the runtime
definition. `document-diff` and `document-inspect` are **read-only artifact
operations**: they are public and dispatchable, but intentionally have no
runtime stages and must not be counted as stage coverage.

`FULL_STAGE_IDS` is authoritative and ordered as follows:

```text
resolve-config -> resolve-template -> resolve-context -> resolve-assets
-> validate-contracts -> ingest-sources -> normalize-sources
-> compile-structure -> generate-visuals -> compose-cover -> build-docx
-> build-html -> build-pdf -> structural-audit -> editorial-review
-> evidence-review -> consistency-review -> accessibility-review
-> visual-review -> reproducibility-check -> record-provenance
-> package-release -> publish-draft
```

`build` runs the full `document` pipeline by default and writes successful formats to `output/current/` only when its selected policy permits publication. Use `--pipeline document-build` to execute only the registered build boundary without publication. `verify` excludes the release-only `package-release` and `publish-draft` stages by default; use `--pipeline document-verify` for the registered verification boundary, which also does not publish. `document release` runs the full pipeline under the release policy. Its `cli-verify-*` run does not overwrite the build attestation. `package` takes an explicit ZIP output path and `publish` takes an explicit artifact destination; the managed release pipeline writes its package under `output/release/`. The shared composition constructs the native `PipelineService` and its stage operations for application entry points. Stages may report `skipped` when no applicable input exists (for example, no visual specs or no cover); injected partial operation sets remain useful for failure tests, not the normal application setup.

## Format selection

Use repeatable options when the same source must produce multiple formats:

```bash
uv run docs document build --format docx --format html --json
```

Only requested renderers are executed. A missing optional PDF/visual capability is visible in the report; draft can degrade, while strict/release turn required gaps into errors.

## Read-only artifact operations

`inspect` computes an identity report without modifying the artifact. `diff`
compares SHA-256 and adds a UTF-8 unified diff when both inputs are
text-readable. These two operations are deliberately separate from the
stage-backed public pipelines above: they inspect or compare existing
artifacts and do not execute a stage DAG. `package` and `publish` validate and
snapshot source bytes before writing through temporary paths; they do not
follow symlinked or escaped paths.

## Inspecting pipeline contracts

Use `docs document plan --pipeline document-build --json` to inspect the ordered stages, external artifacts, and contracts without executing or publishing a build. The command uses the same registered DAG that `build` and `verify --pipeline` execute.

## Pipeline ownership

`PipelineService` is the application-facing pipeline capability: it registers the stage graph, executes it, applies outcome policy, and coordinates publication. The private `_PipelineExecutor` is an internal mechanical executor used by the service; it is not a supported integration point. The removed `PipelineRuntime` application class and `PipelineService.run` API are not part of the current contract. Worker jobs retain a worker-specific runtime protocol/factory for job lifecycle integration, but that protocol delegates to the shared application pipeline rather than defining another document pipeline.
