# Migrating to Docs Harness v2

V2 is the target runtime. During migration it is additive and keeps legacy
artifacts isolated; the legacy pipeline is a finite compatibility bridge, not a
second implementation path for new integrations. Remove that bridge only after
the migration checklist for every workspace and consumer is green.

## Command mapping

| Existing workflow | V2 replacement | Migration note |
|---|---|---|
| `docs doc new <id>` | `docs document create <id>` | Same workspace document service; choose template/title explicitly when needed. |
| `docs pipeline ingest` | `docs document ingest` | Native v2 source report; does not author sections. |
| `docs pipeline prep` | `docs document prepare` | Adds normalization and `docs.structure/v2`; source preparation is repeatable. |
| `docs pipeline assemble` | `docs document build --format ...` | Writes verified requested formats under `output/v2/`, not legacy `output/final/`. |
| `docs verify` | `docs document verify --format ...` | Format-specific v2 checks and stage report without publication. |
| Manual artifact copying | `docs document publish ... --policy strict|release` | Requires a matching manifest and verifiable attestation. |
| Ad hoc ZIP creation | `docs document package ...` | Atomic, deterministic package operation over the supplied directory. |

The legacy `docs pipeline` commands remain supported during the migration
window. V2 does not silently invoke them, and every new integration must use
the v2 commands. The bridge can be retired once the document/workspace
inventory has no remaining legacy consumers.

## Safe sequence

1. Keep the existing document and legacy output untouched.
2. Run `document status --json` and record the active document/template.
3. Run `document ingest --json`, then `document prepare --json`.
4. Review/author section Markdown; do not edit generated `sections/ingested` or v2 structure as prose.
5. Run `document verify` for each target format under `draft` first.
6. Resolve capability or contract warnings; rerun under `strict`.
7. Run `document build --policy strict` and inspect its manifests, QA, and provenance.
8. Publish only the verified artifact from `output/v2/` under `release`.

## Compatibility boundary

V2 uses the existing workspace and template data model but has a separate output and provenance boundary. The `v2` command alias is retained while callers migrate to `document`. There is no automatic promotion from `output/v2/` to `output/final/`; choose publication explicitly. Public stage-backed boundaries can also be executed independently with `--pipeline`, for example `docs document build --pipeline document-package` and `docs document build --pipeline document-publish` after a verified build.

Treat `unsupported` stages in the runtime report as migration inventory, not as proof that those stage behaviors exist. A rollout is complete only when the stages and capabilities required by the document's policy are implemented and verified.
