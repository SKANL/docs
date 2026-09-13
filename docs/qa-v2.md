# Docs Harness v2 QA

QA is layered. A green command means the applicable runtime contracts passed; it does not mean every optional visual tool was available.

## Visual baselines

Visual snapshots are opt-in. Configure a baseline directory and an explicit
similarity tolerance in the document configuration:

```json
{
  "visual_qa": {
    "baseline_dir": "qa/baselines",
    "minimum_similarity": 0.75
  }
}
```

QA compares each rendered `*.png` page with the same-named baseline without
rewriting either directory. It reports `visual.baseline_changed`,
`visual.baseline_missing`, `visual.baseline_extra_page`, or
`visual.baseline_unreadable` with the affected page. Draft mode reports these
as warnings; strict and release mode make them blocking errors. Updating a
baseline is an explicit authored operation outside verification.

## Local checks

```bash
uv sync --locked
uv run ruff check .
uv run mypy
uv run pytest -q --cov=src --cov-report=term-missing --cov-fail-under=93
uv run pytest tests/architecture -q
```

Use `uv run docs doctor` to see optional executables and their versions. For a document, run `document verify` for the requested formats and inspect the JSON stage results, warnings, capabilities, and verification payload.

## Verification layers

- **Contract QA:** stage definitions, artifact names, dependencies, and outcomes are deterministic and validated before execution.
- **Source QA:** ingest, normalization, and compiled structure are reported as `docs.sources/v2` and `docs.structure/v2` artifacts.
- **DOCX QA:** format audit plus configured document QA adapters.
- **HTML QA:** UTF-8 decoding and exactly one HTML root and body root.
- **PDF QA:** `%PDF-` signature, readable reopen, at least one page, and valid page render dimensions.
- **Provenance QA:** source/output hashes and manifest attestation are recorded only after accepted execution.
- **Publication QA:** strict/release policy, manifest identity, current input identity, attestation, containment, and atomic transform all pass.

## Degradation rules

Draft mode may preserve permitted optional gaps as warnings and never publishes. Strict and release promote warnings or required capability gaps to errors. `unsupported` is always visible in stage results; it is not silently converted into a completed implementation. Missing optional previews or tools must remain visible in reports.

## CI evidence

The repository workflow runs lint, type checks, tests, architecture invariants, and a full optional-toolchain job. The toolchain job is important because the normal check job intentionally exercises degradation without every optional tool. See [ci-v2.md](ci-v2.md) for the exact workflow.

## Visual baseline snapshots

QA compares rendered previews against `visual_qa.baseline_dir` when configured.
Updating a baseline is an explicit authoring operation and never happens during
`build` or `verify`:

```text
docs document baseline <preview-dir> --destination <baseline-dir>
docs document baseline <preview-dir> --destination <baseline-dir> --update
```

The command validates every PNG, stages the complete set in a scratch directory,
and publishes the directory atomically. An existing baseline is preserved unless
`--update` is supplied; incomplete or corrupt previews are never published.

