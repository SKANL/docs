# Migrating to Docs Harness v2

V2 is the target runtime. During migration it is additive and keeps current
artifacts isolated; the alternate pipeline is a finite native bridge, not a
second implementation path for new integrations. Remove that bridge only after
the migration checklist for every workspace and consumer is green.

## Command mapping

| Existing workflow | V2 replacement | Migration note |
|---|---|---|
| `docs doc new <id>` | — | Canonical workspace document creation command; choose template/title explicitly when needed. |
| `docs document ingest` | `docs document ingest` | Native v2 source report; does not author sections. |
| `docs document prepare` | `docs document prepare` | Adds normalization and `docs.structure/v2`; source preparation is repeatable. |
| `docs document build` | `docs document build --format ...` | Writes verified requested formats under `output/current/`, not unverified output. |
| `docs verify` | `docs document verify --format ...` | Format-specific v2 checks and stage report without publication. |
| Manual artifact copying | `docs document publish ... --policy strict|release` | Requires a matching manifest and verifiable attestation. |
| Ad hoc ZIP creation | `docs document package output/current output/release/release.zip` | Atomic, deterministic package operation that creates an explicit release artifact. |

The old duplicate document-creation command (`document create`) is removed; use `docs doc new`. `PipelineService` is the sole application pipeline owner. The private executor is an implementation detail, not a public integration point.

## Safe sequence

1. Keep the existing document and current output untouched.
2. Run `document status --json` and record the active document/template.
3. Run `document ingest --json`, then `document prepare --json`.
4. Review/author section Markdown; do not edit generated `sections/ingested` or v2 structure as prose.
5. Run `document verify` for each target format under `draft` first.
6. Resolve capability or contract warnings; rerun under `strict`.
7. Run `document build --policy strict` and inspect its manifests, QA, and provenance.
8. Publish only the verified artifact from `output/current/` under `release`.

## Native boundary

V2 uses the existing workspace and template data model but has a separate output and provenance boundary. The `document` command is the only public pipeline surface. Build writes verified artifacts to `output/current/`; package and publish create explicit release outputs, conventionally under `output/release/`. There is no automatic release transition: build, verify, package, and publish remain separate commands. Public stage-backed boundaries can also be executed independently with `--pipeline`, for example `docs document build --pipeline document-package` and `docs document build --pipeline document-publish` after a verified build.

The shared factory in `src/docs/composition.py` constructs the typed application dependencies and `PipelineService`; CLI, API, and worker entry points reuse it. API transport configuration and worker polling/queue/lease options remain process-specific. `unsupported` is reserved for deliberately incomplete injected composition or an unavailable optional capability; it is not an acceptable result for a release build. Use `document status --json` and fail CI when the selected release pipeline contains an unsupported stage.
