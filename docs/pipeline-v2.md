# Docs Harness v2 Pipeline

Use this page as the operational path. The source stages are explicit commands; build and verify then execute the contract-driven runtime.

## Quick path

```bash
uv run docs document create report --template technical-report-srs
uv run docs document status --json
uv run docs document ingest --json
uv run docs document prepare --json
# author section Markdown under the document's sections/ directory
uv run docs document build --format docx --policy strict --json
uv run docs document verify --format docx --policy strict --json
uv run docs document inspect documents/report/output/v2/report.docx --json
uv run docs document package documents/report/output/v2 release.zip --json
uv run docs document publish documents/report/output/v2/report.docx published/report.docx --policy release --json
```

`document ingest` converts inbox material. `document prepare` repeats ingest, normalizes ingested Markdown, and writes the compiled source structure. Both commands persist `docs.sources/v2` reports below `runs/`; they do not author section prose.

## Source preparation reports

| Operation | Report | Stage(s) | Main derived files |
|---|---|---|---|
| `ingest` | `runs/v2-ingest.json` | `ingest-sources` | `sections/ingested/*`, registered assets, ingest report data |
| `prepare` | `runs/v2-prepare.json` | `ingest-sources`, `normalize-sources`, `compile-structure` | normalized ingested Markdown and `sections/v2-structure.json` |

Each report has `schema: "docs.sources/v2"`, `document_id`, `succeeded`, ordered `stages`, and `artifacts`. A source command exits non-zero when its report is unsuccessful.

## Stage results

Build and verify return a runtime report containing `capabilities`, `execution`, `provenance`, and `succeeded`. `execution.results` is ordered and each result contains:

- `stage`: stable stage identifier;
- `ok`: whether the stage is accepted by the active policy;
- `outcome`: `succeeded`, `failed`, `skipped`, or `unsupported`;
- `artifacts`: artifact records emitted by the stage;
- `warnings` and `errors`: visible policy/degradation evidence.

A `failed` stage stops its downstream dependency chain. A visible optional `unsupported` result is not the same as a successful implementation; strict/release publication still fails when a required capability or contract is unavailable. The runtime only records successful run hashes after the complete accepted execution.

## Full stage plan

`FULL_STAGE_IDS` is authoritative and ordered as follows. The public boundaries
below are registered as validated sub-DAGs and reuse the same stage handlers;
they are not separate format-specific implementations:

```text
source-ingest | document-prepare | document-build | document-verify
| document-publish | document-package | document-diff | document-inspect
```

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

`build` excludes no publication stages and writes successful formats to `output/v2/`. `verify` excludes `publish-draft` and `package-release`; its `cli-verify-*` run does not overwrite the build attestation. The workspace bridge may leave selected stages as explicit no-op contract stages until their adapter is migrated.

## Format selection

Use repeatable options when the same source must produce multiple formats:

```bash
uv run docs document build --format docx --format html --json
```

Only requested renderers are executed. A missing optional PDF/visual capability is visible in the report; draft can degrade, while strict/release turn required gaps into errors.

## Read-only artifact operations

`inspect` computes an identity report without modifying the artifact. `diff` compares SHA-256 and adds a UTF-8 unified diff when both inputs are text-readable. `package` and `publish` validate and snapshot source bytes before writing through temporary paths; they do not follow symlinked or escaped paths.
