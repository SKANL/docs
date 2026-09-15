# Docs Harness v2 Contracts

V2 contracts make stage completion, artifact identity, and publication evidence machine-checkable. JSON is deterministic: keys are sorted and content-addressed values are stable.

## Pipeline contracts

A `PipelineDefinition` contains unique `ArtifactContract` entries and `StageSpec` entries. Artifact names and stage names use lowercase identifiers (`[a-z0-9][a-z0-9._-]*`). A stage declares `requires`, `produces`, `fail_fast`, and `optional`; the definition rejects unknown artifacts, duplicate producers, duplicate references, unavailable dependencies, and cycles.

The current service creates one completion artifact per stage (`<stage>-complete`). The contract is deliberately separate from file paths: a stage may emit an `ArtifactRecord` with a contract name, path, lowercase hexadecimal SHA-256, and optional metadata.

## Stage result contract

```json
{
  "stage": "structural-audit",
  "ok": true,
  "outcome": "succeeded",
  "artifacts": [],
  "warnings": [],
  "errors": []
}
```

Valid outcomes are `succeeded`, `failed`, `skipped`, and `unsupported`. `skipped` and `unsupported` are visible, non-failing results; policy and required downstream contracts determine whether the overall run can publish.

## Build manifest

Each build artifact has a sibling manifest with schema `docs.build/v2`:

```json
{
  "schema": "docs.build/v2",
  "document_id": "report",
  "source_hash": "<sha256>",
  "template_hash": "<sha256>",
  "config_hash": "<sha256>",
  "context_hash": "<sha256>",
  "asset_hashes": {"assets/logo.png": "<sha256>"},
  "renderer_versions": {"docx": "<identity>"},
  "artifacts": [{"path": "<absolute-path>", "sha256": "<sha256>", "state": "ready"}],
  "verification": {"passed": true},
  "provenance_run": "<run-id>"
}
```

Publication requires non-empty document identity, SHA-256 source/template/config/context values, valid artifact identities in `ready` or `published` state, passed verification, renderer identity, and a provenance run. Manifest artifacts are sorted by path when serialized.

## Source reports

`document ingest` and `document prepare` return `docs.sources/v2` reports with `document_id`, `succeeded`, ordered `stages`, and relative `artifacts`. `prepare` includes `ingest-sources`, `normalize-sources`, and `compile-structure`; its `sections/v2-structure.json` has schema `docs.structure/v2`, the document id, configured structure parts, and ingested source paths.

## Atomicity and path rules

Rendered and published outputs are built in temporary locations and replaced only after expected outputs exist and validation succeeds. Publication requires the source and manifest to be contained by the document's `output/current/`; destination must remain inside the document root. Packaging rejects symlinked or escaped source entries. Existing destinations are not replaced by a failed transform.

