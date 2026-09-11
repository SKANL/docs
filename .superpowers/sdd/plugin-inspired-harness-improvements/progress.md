# SDD ledger — plan: docs/superpowers/plans/2026-09-11-plugin-inspired-harness-improvements.md

Baseline: 1806 passed, 5 skipped.

Preflight: tasks 1-3 establish contracts/provenance/atomic transforms; tasks 4-5 consume artifact reports; tasks 6-8 extend templates/review/pipeline; tasks 9-10 document and regenerate CISSP. No spec file was supplied beyond the plan.

Ruling: Implement in four sequential writer batches to keep changes reviewable while preserving the plan boundaries; each batch must pass focused tests before the next.

Task 1-3: complete
- Added stable domain models (`ArtifactState`, `ArtifactRef`, `VerificationFinding`, `VerificationReport`).
- Added `ProvenanceLedger` with `docs.provenance/v1`, canonical SHA-256 entry hashes, legacy `events` migration, and tamper verification.
- Added `TransformSpec`, `TransformResult`, `TransformPort`, and `AtomicTransform`; it validates complete scratch outputs and preserves a prior published directory if production fails.
- RED: `uv run pytest tests/unit/domain/test_artifacts.py tests/unit/domain/test_provenance.py tests/integration/test_atomic_transform.py -v` failed at collection because the three new modules did not exist.
- GREEN: same focused command passed: 7 passed.
- Related suite: `uv run pytest tests/unit/domain tests/integration/test_atomic_transform.py -q` passed: 686 passed.
Task 4-5: pending
Task 6-8: pending
Task 9-10: pending

## Atomic publication fix
- Root cause: replacing a non-empty directory needs two renames on Windows; termination between them can leave no published target.
- Replaced directory swapping with immutable `.versions/<id>` directories and an atomically replaced `.current` file pointer. The prior pointer and its version remain reachable until the new pointer is installed.
- Added tests for pointer-swap failure preservation and file output-target rejection.
- Focused: `uv run pytest tests/integration/test_atomic_transform.py -v` — 5 passed.
- Related: `uv run pytest tests/unit/domain tests/integration/test_atomic_transform.py -q` — 688 passed.
