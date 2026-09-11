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
Task 4-5: complete
Task 6-8: pending
Task 9-10: pending

## Atomic publication fix
- Root cause: replacing a non-empty directory needs two renames on Windows; termination between them can leave no published target.
- Replaced directory swapping with immutable `.versions/<id>` directories and an atomically replaced `.current` file pointer. The prior pointer and its version remain reachable until the new pointer is installed.
- Added tests for pointer-swap failure preservation and file output-target rejection.
- Focused: `uv run pytest tests/integration/test_atomic_transform.py -v` — 5 passed.
- Related: `uv run pytest tests/unit/domain tests/integration/test_atomic_transform.py -q` — 688 passed.

## Direct-path publication correction
- Re-review found the pointer-version design broke the planned public output paths. It is superseded.
- `AtomicTransform` now stages files under the output directory and uses `os.replace` per declared file into `output_dir/<relative path>`; interruption leaves each path either the prior complete file or a complete replacement.
- Direct-path and injected file-replacement-failure tests pass; file-as-output-directory rejection remains covered.
- Focused: `uv run pytest tests/integration/test_atomic_transform.py -v` — 5 passed.
- Related: `uv run pytest tests/unit/domain tests/integration/test_atomic_transform.py -q` — 688 passed.

## Publication rollback correction
- Re-review found that sequential direct replacements could leave a mixed generation after a late replacement failure.
- Before publication, `AtomicTransform` snapshots every target file or its absence. Any ordinary `os.replace` failure restores all declared targets using staged restore files plus atomic replacement; transient scratch and restore files are cleaned.
- Process-kill atomicity across multiple direct files is explicitly not promised; ordinary transform failures leave no mixed generation.
- Added injected second-replacement failure coverage proving both prior direct files are restored. File-as-output-directory rejection remains covered.
- Focused: `uv run pytest tests/integration/test_atomic_transform.py -v` — 6 passed.
- Related: `uv run pytest tests/unit/domain tests/integration/test_atomic_transform.py -q` — 689 passed.

## Task 4-5: complete
- Added `RenderProfile`, `RenderVerificationPort`, and `RenderVerificationService`; artifact identity is SHA-256 bound before format-specific verification.
- Added format-neutral verification adapter: PDF pages are opened/rendered with pypdfium2, per-page validity/blank-page findings and deterministic previews are emitted; DOCX uses python-docx for readability/page dimensions and degrades when optional page rendering is absent; HTML and image opening/dimensions are also covered.
- Added `StructuralAuditPort`, `StructuralAuditService`, and declarative DOCX/PDF structural checks for headings/section order, table and image minima, captions, references, metadata, PDF readability, and page dimensions. Editorial review remains separate.
- QA can accept an optional render-verification service and add its findings to `qa-report.md`; current callers retain the existing constructor behavior. Composition-root wiring remains intentionally deferred to Task 7.
- Fixed the pending rollback hygiene minor: restore staging files are removed even when `os.replace` fails during rollback.
- RED: focused service tests initially failed at missing module imports; adapter and rollback-cleanup tests then failed before implementation/fix.
- GREEN: `uv run pytest tests/unit/domain/test_artifacts.py tests/unit/application/test_render_verification_service.py tests/unit/application/test_structural_audit_service.py tests/unit/infrastructure/test_render_verification_adapter.py tests/unit/infrastructure/test_structural_audit_adapter.py tests/integration/test_atomic_transform.py tests/integration/test_qa_service.py tests/integration/test_format_audit_service.py -q` passed (with one pre-existing skip).
- Static checks: focused `ruff` passed; `mypy` passed for 10 source files.

## Task 4-5 review corrections: complete
- Empty rendered pages now honor `RenderProfile.allow_blank_pages`: prohibited pages are errors; explicitly allowed pages remain warnings.
- Verification rejects profile/actual format mismatches, re-hashes before and after inspection, and fails with `artifact.identity_changed` on mutation.
- Strict QA includes a failed render-verification report in both the QA report and its final gate; constructor compatibility is preserved.
- Structural page-size rules now accept JSON arrays as well as tuples. `require_previews` is explicitly optional by default and becomes an error when requested but unavailable.
- RED tests covered blank-page policy, format mismatch, artifact mutation, strict QA gating, and JSON page-size validation.

## Task 6: complete
- Added the opt-in `TemplateContract` model under `Template.template_contract` with declarative page geometry, styling, component, editable-slot, asset, fidelity-check, and degradation fields.
- Legacy templates omit the contract from serialized config and retain byte-compatible evidence manifests and per-section contract hashes when no template contract is declared.
- Declared template contracts are now bound into rules manifests and rules-hash fallback payloads through a separate `template_contract_hash`; validation also reports near-miss contract keys without rejecting deliberate extensions.
- RED: `uv run pytest tests/unit/domain/models/test_template.py tests/unit/domain/test_template_validation.py tests/integration/test_evidence_service.py -q` failed during collection because `TemplateContract` did not exist.
- GREEN: `uv run pytest tests/unit/domain/models/test_template.py tests/unit/domain/test_template_validation.py tests/unit/domain/test_evidence.py tests/integration/test_evidence_service.py -q` — 109 passed.
- Static checks: focused `ruff` passed; `mypy` passed for 4 source files.

## Task 6 review corrections: complete
- Root cause: `Template.template_contract` defaulted to an empty model, so a legacy template's serialized config carried default contract fields and changed evidence/provenance despite no opt-in declaration.
- `template_contract` now defaults to `None`; evidence canonicalizes absent, `{}`, and default-only legacy serializations as no declaration. Legacy manifests omit template-contract fields and section hashes remain section-only.
- Template-wide fidelity data is bound independently as `template_contract_hash` in the rules manifest and fallback `rules_hash`; it is no longer folded into per-section `contract_hash` values.
- Added regression coverage across legacy template serialization -> config -> build_rules manifest -> section provenance, fallback rules hashing, and deliberately nested extension data.
- RED: legacy serialization and provenance tests failed with the empty default contract present in the model and manifest.
- GREEN: `uv run pytest tests/unit/domain/models/test_template.py tests/unit/domain/test_template_validation.py tests/unit/domain/test_evidence.py tests/integration/test_evidence_service.py -q` — 112 passed.
- Static checks: focused `ruff` passed; `mypy` passed for 4 source files.
- Reviewer re-check approved all Important/Critical findings; aligned the empty-contract comment with canonicalization behavior and renamed the provenance test for its section-only hash semantics. No review artifact files retained.

## Task 7: complete
- Wired render verification and structural audit services at the composition root without changing the existing stage plan. `qa-docx` now treats an error-severity render verification report as a blocking QA failure; warning-only reports continue in non-strict mode. When a template declares a contract, the optional structural audit runs at that same final QA gate and blocks only on its existing error findings.
- The compatible adapter is intentionally additive: `PipelineService.structural_audit_service` defaults to `None`, so direct callers and templates without an opt-in contract retain prior behavior.
- RED: `uv run pytest tests/integration/test_pipeline_service.py -q -k 'wired_render_verification'` failed because an error report still let assemble pass.
- GREEN: same focused command — 2 passed, 41 deselected.
- Static checks: `uv run ruff check src/docs/application/pipeline.py src/docs/application/qa.py src/docs/cli/_shared.py tests/integration/test_pipeline_service.py` passed; `uv run mypy src/docs/application/pipeline.py src/docs/application/qa.py src/docs/cli/_shared.py` passed.
- Runtime wiring: `uv run python -c "from docs.cli._shared import Deps; Deps(); print('Deps wiring ok')"` passed.
- Review: approved with no Important findings; only minor coverage suggestions were recorded for future work. Scratch review diff removed; no scope expansion applied.
