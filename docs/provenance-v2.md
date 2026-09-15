# Docs Harness v2 Provenance and Attestation

V2 provenance is separate from the legacy ledger. It is content-bound evidence for a specific run, manifest, and artifact byte set.

## Ledger

The native ledger is `runs/v2-provenance.json` and has `runs` and `attestations` maps. Each run records a stable run id, input paths and SHA-256 values, and output paths and SHA-256 values. Paths inside the document root are stored relative to the ledger directory; external paths are stored resolved.

The ledger writes canonical JSON through a temporary file and atomic replacement. Updates are serialized by a process lock. A stale lock is reclaimable only when its owner metadata proves it is old and the process is no longer alive.

## Manifest and attestation

A successful build writes a `docs.build/v2` manifest beside each output. `BuildManifest.attestation()` wraps that manifest as:

```json
{
  "schema": "docs.attestation/v2",
  "manifest": {"schema": "docs.build/v2"},
  "sha256": "<hash-of-canonical-manifest>"
}
```

The attestation is recorded against the build run. Standalone `publish` verifies both equality with the recorded manifest and the run's current input/output hashes. It also recomputes current source, template, config, context, asset, and renderer identities before copying bytes.

## What is and is not proven

A valid attestation proves that the recorded manifest and hashed files have not drifted since the run. It does not prove editorial truth, visual quality beyond the checks that ran, or availability of an optional tool that was skipped. Those claims belong in the verification report and policy result.

`document verify` performs checks without publishing and uses a separate verify run id. It does not overwrite an existing build attestation. Do not hand-edit manifests or ledger JSON; changed bytes will fail publication validation.

## Inspecting evidence

```bash
uv run docs document status --json
uv run docs document inspect documents/report/output/v2/report.docx --json
uv run docs document publish documents/report/output/v2/report.docx published/report.docx --policy release --json
```

When publish rejects an artifact, fix the source/toolchain drift and rebuild. Do not bypass the manifest or copy the file directly into a release directory.
