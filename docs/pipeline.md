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
uv run docs document inspect documents/report/output/current/report.docx --json
uv run docs document package documents/report/output/current release.zip --json
uv run docs document publish documents/report/output/current/report.docx published/report.docx --policy release --json
```

`document ingest` converts inbox material. `document prepare` repeats ingest, normalizes ingested Markdown, and writes the compiled source structure. Both commands persist `docs.sources/v2` reports below `runs/`; they do not author section prose.

## Source preparation reports

| Operation | Report | Stage(s) | Main derived files |
|---|---|---|---|
| `ingest` | `runs/v2-ingest.json` | `ingest-sources` | `sections/ingested/*`, registered assets, ingest report data |
| `prepare` | `runs/v2-prepare.json` | `ingest-sources`, `normalize-sources`, `compile-structure` | normalized ingested Markdown and `sections/v2-structure.json` |

Each report has `schema: "docs.sources/v2"`, `document_id`, `succeeded`, ordered `stages`, and `artifacts`. This shape is also mandatory for failure reports: construction, invocation, malformed-result, and empty-stage failures retain the selected document's `document_id`. A source command exits non-zero when its report is unsuccessful.

The flat native command routes `pipeline ingest` to
`SourcePipeline.ingest` and `pipeline prepare` to
`SourcePipeline.prepare`. It projects each v2 stage into the existing
current summary shape (`stage_set`, `strict`, `passed`, and `stages`) while
retaining the complete v2 report, including warnings, errors, and artifacts,
in each stage's `detail`. It forwards `--strict` when the selected callable
accepts `strict`; `prepare` currently reports strict as advisory because its
native operation does not accept that argument. The current `pipeline prep`
route remains unchanged.

## Stage results

Build and verify return a runtime report containing `capabilities`, `execution`, `provenance`, and `succeeded`. `execution.results` is ordered and each result contains:

- `stage`: stable stage identifier;
- `ok`: whether the stage is accepted by the active policy;
- `outcome`: `succeeded`, `failed`, `skipped`, or `unsupported`;
- `artifacts`: artifact records emitted by the stage;
- `warnings` and `errors`: visible policy/degradation evidence.

A `failed` stage stops its downstream dependency chain. A visible optional `unsupported` result is not the same as a successful implementation; strict/release publication still fails when a required capability or contract is unavailable. The runtime only records successful run hashes after the complete accepted execution.

## Traceability boundary

`docs/traceability.json` keeps four claims separate for every
runtime stage:

1. **Declaration** — the stage is named by `FULL_STAGE_IDS`.
2. **Runtime wiring** — `PipelineService` registers a handler for the stage.
3. **Executable evidence** — an integration test exercises and asserts the stage.
4. **Observed outcome** — that test records whether the stage succeeded,
   remained unsupported, or was not observed.

Each nested claim has a strict shape: declaration and runtime wiring require
non-empty `source` fields; covered executable evidence requires a `test`,
while not-covered evidence requires a `reason`; observed outcomes always carry
a `test` field (or `null` when not observed). A succeeded outcome is valid only
when executable evidence is covered and points to the same test. An unsupported
outcome is valid only when executable evidence is not-covered and includes the
test that observed the unsupported result. The integration contract also
compares the JSON public-pipeline classification with the runtime
`PUBLIC_PIPELINES` catalog, keeping stage-backed boundaries distinct from the
read-only `document-diff` and `document-inspect` operations.

A declared and wired stage is not automatically covered. The traceability file
deliberately leaves untested stages as `not-covered` and `not-observed` rather
than inferring support from the registry.

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

`build` runs the full `document` pipeline by default and writes successful formats to `output/current/`. Use `--pipeline document-build` to execute only the registered build boundary without publication. `verify` excludes `publish-draft` and `package-release` by default; use `--pipeline document-verify` for the registered verification boundary. Its `cli-verify-*` run does not overwrite the build attestation. The CLI composition root supplies handlers for every declared stage; a stage is `skipped` only when its document has no applicable input (for example, no visual specs or no cover). Partial programmatic service maps are intentionally fail-closed and are not the normal runtime.

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

## Flat CLI migration boundary

The native policy for the unprefixed `retired pipeline command` command
is intentionally explicit and finite. `ingest` and `prepare` are routed through the
native v2 source pipeline and its result is adapted back to the current summary
shape (`stage_set`, `strict`, `passed`, and `stages`). `assemble` now routes
through the native v2 build runtime and projects its execution report back to
the current summary shape. `prep` and `all` now execute through the native
`FlatPipelineV2Adapter`, which reuses injected stage operations while
owning ordering, fail-fast behavior, and the stable flat summary. Unknown stage
sets remain on the current service until their output and publication semantics
have equivalent v2 coverage. This policy is declared in
`removed native module`; it is not inferred from
the public v2 catalog. Consequently, existing exit codes and JSON/human output
contracts remain stable while migration proceeds incrementally.

For the flat `ingest` route, `--strict` is forwarded when the selected v2
operation declares that keyword. If the adapter does not accept it, the command
does not silently discard the flag: it keeps the result degradable and emits a
structured `pipeline.strict_advisory` warning in JSON. A v2 report without any
stage is always a native failure with `pipeline.empty_v2_report`.
