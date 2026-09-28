# Docs Harness X20 Architecture

Canonical X20 is the contract-driven public surface for preparing sources, building, checking, inspecting, comparing, packaging, and publishing document artifacts. It keeps source inputs separate from derived outputs and records content-bound evidence before publication.

## Public surface

Run from the harness checkout or use the installed `docs` entry point. `doc init` creates a workspace and `doc new` is the single document-creation command. The `document` group is the canonical pipeline surface; `source ingest` is the source-specific public boundary.

| Command | Purpose | Writes |
|---|---|---|
| `doc new <id> [--template T] [--title X]` | Create and activate a workspace document. | Document source structure. |
| `document release [--format F]... [--policy release] [--json]` | Run the complete verified build/package/publication pipeline for the active document. | Verified X20 artifacts, manifests, provenance, and release package. |
| `document ingest [--json]` | Convert the active document's inbox sources through the native X20 source stage. | Ingested sections/assets and `runs/v2-ingest.json`. |
| `document prepare [--json]` | Run ingest, normalization, and structure compilation in order. | Prepared sources, `sections/v2-structure.json`, and `runs/v2-prepare.json`. |
| `document status [--json]` | Report domain status plus X20 capabilities, manifests, and provenance details. | No source changes; status may read existing run data. |
| `document build [--format F]... [--policy P] [--json]` | Run the X20 plan; the full pipeline writes verified requested formats into `output/current/` only when its policy permits publication. | Derived artifacts, sidecar manifests, QA data, and X20 provenance. |
| `document verify [--format F]... [--policy P] [--json]` | Run format checks without publishing. | Verification output only; it does not create a build attestation for `cli-verify-*`. |
| `document inspect <artifact> [--json]` | Report path, media type, size, and SHA-256. | Nothing. |
| `document diff <left> <right> [--json]` | Compare identities and, for UTF-8 files, return a text diff. | Nothing. |
| `document package <dir> <zip> [--json]` | Package a verified X20 artifact directory as a deterministic ZIP through a temporary file. | The requested ZIP after close succeeds. |
| `document publish <source> <destination> [--policy strict\|release] [--json]` | Publish one attested X20 artifact and its manifest atomically. | Destination artifact and manifest. |

`--format` is repeatable and currently accepts the configured renderer formats (`docx`, `html`, `pdf`). `build` defaults to the document configuration when no format is supplied. `status`, `ingest`, and `prepare` use the active document selected by the workspace context.

## Boundaries

Durable source inputs are `document.json`, section Markdown, resolved context, template/configuration, and workspace assets. Rendered DOCX/HTML/PDF files, manifests, QA reports, ZIP packages, and published copies are derived artifacts. Derived artifacts never replace source Markdown.

The native runtime does not silently fall back to an alternate pipeline. The full `document` build pipeline writes verified artifacts under `output/current/` only when the selected policy and pipeline permit publication; `document-build` and `document verify` do not publish artifacts. `document release` runs the full pipeline under the release policy, where the release stages are eligible. `docs document package` takes an explicit output path, while `docs document publish` takes an explicit destination; the managed release pipeline uses `output/release/` for its package artifact. These are separate transitions: building, verifying, packaging, and publishing have distinct side effects. Canonical X20 source preparation intentionally reuses existing ingest/render/audit adapters through ports; this is an implementation bridge, not a plugin dependency.

## Pipeline kernel

The exported `FULL_STAGE_IDS` declaration has 23 stages. It is the registry's
complete stage inventory, not the execution order:

```text
resolve-config
resolve-template
resolve-context
resolve-assets
validate-contracts
ingest-sources
normalize-sources
compile-structure
generate-visuals
compose-cover
build-docx
build-html
build-pdf
structural-audit
editorial-review
evidence-review
consistency-review
accessibility-review
visual-review
reproducibility-check
record-provenance
package-release
publish-draft
```

The registered `PipelineDefinition.plan()` is the runtime execution order:

```text
resolve-config
resolve-template
resolve-context
resolve-assets
validate-contracts
ingest-sources
normalize-sources
compile-structure
generate-visuals
compose-cover
build-docx
build-html
build-pdf
structural-audit
editorial-review
evidence-review
consistency-review
accessibility-review
visual-review
reproducibility-check
record-provenance
package-release
publish-draft
```

The published execution report preserves that plan sequence. The composition
root registers native handlers for visual generation, declarative cover
validation/composition, multiformat rendering, review, provenance, packaging,
and publication. A document without visual specs or a cover reports an
intentional `skipped` stage; it is not an unsupported implementation. A
configured cover is checked for unresolved slots and image assets before the
renderer runs, and strict/release policies promote those findings to blocking
errors. A failed visual stage blocks its dependent cover and document build.

The kernel validates stage names, artifact contracts, dependency availability, duplicate producers, and cycles before execution. Each stage produces a named `<stage>-complete` contract in the current bridge. Execution is fail-fast for a failed required stage. Optional stages can report visible `skipped` or `unsupported` outcomes; policy decides whether those warnings are acceptable.

The shared composition in `src/docs/composition.py` constructs the application dependencies and `PipelineService`. The service owns registration and execution of the stage graph; `_PipelineExecutor` remains a private mechanical executor used by that service, not a second public pipeline API. Do not describe or integrate a separate `PipelineRuntime` application layer. Tests may inject partial operations to exercise dependency failures.

## Policies and capabilities

Capabilities are local executable checks supplied by the composition root and resolved with the host `PATH`. They are reported deterministically; the runtime does not discover or import plugins.

| Policy | Optional gap | Publication |
|---|---|---|
| `draft` | May remain a warning when the active stage contract permits degradation. | Disallowed. `publish-draft` is marked failed. |
| `strict` | Warnings and missing required capabilities become errors. | Allowed only after all gates and attestations pass. |
| `release` | Same error posture as strict. | Allowed; this is the default for standalone `document publish`. |

## Attested publication

A publishable artifact must be under `output/current/`, have a matching `<artifact>.<suffix>.manifest.json`, pass `BuildManifest.validate_for_publication()`, and have a verifiable ledger attestation for the exact manifest and run. The current source/template/config/context/assets/renderer identities must still match. Publication rejects arbitrary paths, missing or failed manifests, draft policy, changed bytes, path escapes, and missing attestations. Temporary files and atomic replacement prevent a failed copy from replacing an existing destination.

## Format boundaries

DOCX uses the existing format audit and QA adapters. HTML is decoded as UTF-8 and must contain exactly one HTML root and one body root. PDF must start with `%PDF-` and reopen with the available PDF reader with at least one page and valid render dimensions. Non-DOCX formats are not silently treated as DOCX. PDF is derived and therefore not byte-deterministic.


## Composition entry points

`compose_application(workspace=None, observability=None)` in `src/docs/composition.py` is the shared application factory. It resolves or accepts the workspace and observability dependencies and returns a typed `ApplicationComposition`. The CLI root (`src/docs/cli/main.py`), API bootstrap, and worker composition use this shared dependency graph rather than assembling duplicate business services.

The factory does not own process lifecycle or transport configuration. CLI argument parsing and local workspace selection, API host/port/auth/CORS settings, and worker queue/lease/polling/retry settings remain specific to those process bootstraps. Keep these operational concerns separate from reusable application composition.
