# Migrating to Docs Harness v2

V2 is the target runtime. During migration it is additive and keeps current
artifacts isolated; the alternate pipeline is a finite native bridge, not a
second implementation path for new integrations. Remove that bridge only after
the migration checklist for every workspace and consumer is green.

## Command mapping

| Existing workflow | V2 replacement | Migration note |
|---|---|---|
| `docs doc new <id>` | `docs document create <id>` | Same workspace document service; choose template/title explicitly when needed. |
| `docs document ingest` | `docs document ingest` | Native v2 source report; does not author sections. |
| `docs document prepare` | `docs document prepare` | Adds normalization and `docs.structure/v2`; source preparation is repeatable. |
| `docs document build` | `docs document build --format ...` | Writes verified requested formats under `output/current/`, not unverified output. |
| `docs verify` | `docs document verify --format ...` | Format-specific v2 checks and stage report without publication. |
| Manual artifact copying | `docs document publish ... --policy strict|release` | Requires a matching manifest and verifiable attestation. |
| Ad hoc ZIP creation | `docs document package ...` | Atomic, deterministic package operation over the supplied directory. |

Current pipeline commands are removed
V2 does not silently invoke them or eagerly construct their aggregate, and
every new integration must use the v2 commands. The bridge can be retired
once the document/workspace inventory has no remaining current consumers.

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

V2 uses the existing workspace and template data model but has a separate output and provenance boundary. The `document` command is the only public pipeline surface. There is no automatic promotion from `output/current/` to `output/published/`; choose publication explicitly. Public stage-backed boundaries can also be executed independently with `--pipeline`, for example `docs document build --pipeline document-package` and `docs document build --pipeline document-publish` after a verified build.

The normal CLI composition root now provides native handlers for the complete stage inventory. `unsupported` is reserved for deliberately incomplete custom composition or an unavailable optional input; it is not an acceptable result for a release build. Use `document status --json` and fail CI when the selected release pipeline contains an unsupported stage.
