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
Task 6-7: complete
Task 8: complete
Task 9: complete
Task 10: complete in external CISSP workspace; the harness repository remains
source-only by design.
- Rebuilt `cissp-dominio-6-interno` and `cissp-dominio-6-entrega` through the
  native v2 pipeline for DOCX, HTML, and PDF with release policy.
- Verified matching v2 manifests/provenance sidecars and PDF rendering:
  internal 15 pages / 0 blank pages; delivery 11 pages / 0 blank pages.
- Preserved the separate internal/delivery source workspaces and labeled
  SVG/PNG visual assets; no authored CISSP sources were copied into this repo.

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

## Task 8: complete
- Added the six-category `ReviewDimension` enum and a backward-compatible `Issue.dimension` field; legacy three-positional-argument callers retain the editorial default while JSON findings now include `dimension`.
- `review-section` remains editorial by default. `review-document` accepts repeatable `--dimension` filtering without changing its existing invocation, while missing document structure is explicitly structural.
- DOCX audit findings now classify document mechanics as structural, layout as visual, and missing figure captions as accessibility, so `docs verify` can distinguish output concerns from content review.
- RED: `uv run pytest tests/unit/domain/test_review.py tests/integration/test_cli_section.py tests/integration/test_format_audit_service.py -q` failed at collection because `ReviewDimension` was absent.
- GREEN: the same focused command passed: 22 passed.
- Static checks: focused `ruff` passed; focused `mypy` passed for 4 source files.

## Task 8 review corrections: complete
- Root cause: the initial dimension change only labeled the DOCX format-audit producer. `StructuralAuditAdapter` still constructed default-editorial issues, and `ReviewService.review_document` rebuilt section issues without carrying their dimension.
- Structural audit findings now use `STRUCTURAL`; missing image captions use `ACCESSIBILITY`. Existing DOCX format-audit visual findings remain `VISUAL`.
- Evidence/APA producers now emit `EVIDENCE`; every cross-section coherence producer emits `CONSISTENCY`. Messages and issue codes are unchanged.
- RED: focused structural, review-document, evidence-filter, and consistency-filter tests failed with default-editorial dimensions or empty filtered results.
- GREEN: `uv run pytest tests/unit/infrastructure/test_structural_audit_adapter.py -q` — 4 passed; `uv run pytest tests/integration/test_review_service.py -q` — 28 passed; `uv run pytest tests/integration/test_cli_section.py tests/integration/test_format_audit_service.py tests/unit/domain/test_review.py -q` — 22 passed.
- Static checks: focused `ruff` and `mypy` passed for the 4 changed source files.

## Task 6 final-suite follow-up: complete
- Added top-level `template_contract` to `SCANNED_CONFIG_KEYS`, matching the new evidence-service config read and restoring architecture-vocabulary coverage.
- RED: `uv run pytest tests/architecture/test_config_vocabulary.py -q` reported the missing `template_contract` declaration.
- GREEN: same architecture suite passed (8 passed); focused `ruff` and `mypy` passed.


## Task 9: documentation — complete
- Updated `AGENTS.md` and `README.md` with native artifact/provenance contracts, scratch/publish behavior, editorial/structural/visual verification, draft versus strict degradation, template fidelity, plugin independence, QA inspection, and renderer/template extension guidance.
- Added a focused AGENTS.md drift guard for the new capability vocabulary.


## Task 9 review corrections: complete
- Clarified the QA evidence contract with the precise `output_qa_dir/<docx-stem>/qa-report.md` and sibling `previews/` paths.
- Added focused AGENTS.md assertions for the QA path and the boundary that Documents, PDF, and Template Creator plugins assist authoring/inspection but are not runtime dependencies.
- Scope intentionally excludes CISSP documents.
- Focused: `uv run pytest tests/unit/test_agents_md_content.py -q` — 12 passed.

## V2 observability follow-up: complete
- Added lazy capability diagnostics with module versions, capability kind,
  requirement text, and draft degradation guidance; the compact capability
  report remains backward compatible.
- Added optional `duration_ms` telemetry to every executed `StageResult` while
  keeping deterministic pipeline JSON free of wall-clock values.
- Added repeatable `--dimension` filtering to `document verify`, aligned with
  the existing legacy verification filter.
- Focused verification: capability tests (7 passed), v2 CLI tests (42 passed),
  pipeline executor/kernel/runtime tests (39 passed), ruff and mypy passed.

## V2 stage boundary follow-up: complete
- Added `StageProviderV2` so v2 composition resolves stage services through a
  single adapter boundary instead of reaching into compatibility containers
  from the CLI orchestration code.
- Added unit coverage for direct-service precedence and missing services.
- Updated architecture documentation to identify this as the migration seam
  toward native stage implementations.
- Focused verification: stage-provider plus v2 CLI tests (44 passed), ruff and
  mypy passed.

## V2 contract naming cleanup: complete
- Renamed the v2 operation contract to `StageOperation` and the dependency
  aggregate to `PipelineStageDependencies`; removed legacy terminology from
  the v2 contract surface without changing compatibility behavior.
- Focused verification: pipeline-service-v2 plus v2 CLI tests (52 passed),
  ruff and mypy passed.

## V2 operation injection: complete
- Replaced the v2 service's named compatibility dependency aggregate with a
  stage-ID-to-operation mapping and an independent publication contract.
- The composition root now normalizes all operations to declarative stage IDs;
  PipelineServiceV2 no longer knows legacy field names or container shape.
- Focused verification: pipeline-service-v2 plus v2 CLI tests (52 passed),
  ruff and mypy passed.

## Legacy boundary isolation: complete
- Moved the legacy `PipelineService` constructor behind the CLI-only
  `LegacyPipelineBridge`; `Deps` keeps this bridge lazy so v2 commands do not
  instantiate the legacy aggregate.
- Documented the bridge as the single removable migration seam in
  `docs/architecture-v2.md` and `docs/migration-v2.md`.
- Regression coverage confirms creating `Deps` does not construct the bridge;
  focused tests passed (10), full suite passed (2129 passed, 5 skipped), and
  ruff/mypy/CodeGraph/CI passed.

## Post-merge CI and runtime hardening: complete
- Routed the normal flat pipeline service path through FlatPipelineV2Adapter
  and removed the obsolete LegacyPipelineExecutor; the CLI compatibility
  facade remains isolated for commands that still expose the historical
  surface.
- Made BuildManifest.identity() independent of workspace absolute paths while
  retaining actual paths in persisted manifests for publication/status checks.
  Legacy attestations are normalized only during comparison and still require
  live artifact digest validation.
- Fixed mutable renderer_versions validation on serialization.
- CI initially exposed 25 path-serialization regressions and then one missed
  mutation-validation regression; both were fixed and the succeeding run
  passed architecture, check, and toolchains.
- Verification: local full suite 2433 passed, 5 skipped; focused pipeline
  service tests 16 passed; CodeGraph index current.

## Legacy facade removal: complete
- Removed the obsolete LegacyPipelineService and LegacyPipelineBridge modules
  and their dedicated compatibility tests.
- Deps now lazily constructs PipelineService directly; core pipeline commands
  no longer expose or route through a legacy facade.
- Added an architecture guard asserting the deleted modules cannot return to
  the runtime.
- Updated architecture/migration docs to describe historical summaries and
  filenames as compatibility projections over the native v2 runtime.
- Verification: focused architecture/CLI/composition suites 190 passed, 3
  skipped; full suite 2429 passed, 5 skipped; ruff and mypy passed; PR CI green.

## Native stage planner naming: complete
- Renamed LegacyStagePlanner to StageOperationPlanner and removed the stale
  legacy module name from the active pipeline runtime.
- The callable contract and ordering remain unchanged; a future slice can
  extract its service-host dependency for stricter hexagonal isolation.
- Focused architecture and pipeline tests: 100 passed, 3 skipped; ruff,
  mypy, and diff checks passed.
## Stage evidence closure: complete
- Added an integration contract journey that executes every `FULL_STAGE_IDS` operation through the native v2 DAG and asserts ordered success, quality-gate completion, and publication.
- Updated `docs/migration-v2-traceability.json` to point all stage evidence at that executable journey; real external renderer coverage remains separately documented as capability-gated.
- Corrected architecture documentation to distinguish the v2 `output/v2` publication boundary from the legacy lifecycle snapshot in `output/final`.
- Focused integration tests: 38 passed; ruff and diff checks passed.
## Manifest identity hardening: complete
- BuildManifest identity now preserves canonical relative artifact paths while stripping workspace-specific absolute roots, preventing same-name path collisions across artifact directories.
- Added RED/GREEN regression coverage and verified manifest/provenance tests.

## Capability registry hardening: complete
- Duplicate tool capabilities now reject incompatible executable/module/degradation definitions while preserving identical duplicate merging and required-policy OR semantics.
- Added RED/GREEN regression coverage.

## Multiformat QA and visual projection: complete
- HTML now receives deterministic CSS from visual themes and generated-cover contracts.
- HTML static inspection checks language, visible heading hierarchy, landmarks, image alt attributes, image validity, and declarative overflow/clipping.
- PDF inspection reports tagged-structure limitations honestly and checks rendered pages, objects, images, dimensions, blank pages, and previews.
- V2 HTML/PDF accessibility and visual stages now use ReviewStageService and RenderVerificationService instead of reopen-only fallbacks.
- Focused integration: 171 passed; ruff, mypy, and diff checks passed.
## Durable transform recovery: complete
- Strengthened v2 publication durability by syncing backups, journals, replacements, and directory metadata where supported.
- Added recovery-before-next-run coverage for a prepared interrupted transaction.
- Documented the honest guarantee: multi-file publication is sequential but journaled, durable, idempotent, and never publishes an unvalidated scratch output.
- Focused atomic-transform tests: 34 passed; ruff, mypy, and diff checks passed.
## Regression closure after multiformat QA: complete
- Updated the architecture guard to inspect the V2 review-stage AST instead of depending on formatting-sensitive source text.
- Added actionable catalog entries for all newly emitted `render.*` findings.
- Focused architecture and issue-code tests: 18 passed; ruff, mypy, and diff checks passed.
- Full-suite run exposed exactly these two stale expectations; no production failures were observed.
## Multiformat visual baselines: complete
- Extended RenderProfile with opt-in baseline directory, similarity threshold, and strictness.
- Reused the existing domain image-similarity comparator for PDF/HTML previews; verification never updates baselines.
- Draft reports baseline drift as warnings; strict/release promote drift to blocking findings.
- Focused baseline/render/review tests: 37 passed; ruff, mypy, and diff checks passed.
## Final recovery and QA closure: complete
- Fixed the atomic publication recovery boundary so a successful replacement followed by a sync/identity failure retains durable recovery evidence and retries safely.
- Made batch publication recovery lock-aware, ownership-checked, copy-before-restore, and retryable when restoration fails; journals are retired only after complete recovery or successful publication.
- Routed DOCX visual review through structured rendered QA, switched PDF reproducibility to semantic page/text/raster comparison, and stabilized preview names while removing stale previews.
- Added catalog entries for the new render and visual findings after the full suite exposed undocumented diagnostics.
- Focused regression tests: 184 passed, 2 skipped; issue-code tests: 9 passed; ruff, mypy, and diff checks passed. A full suite run before the catalog fix was 2489 passed, 1 failed, 5 skipped; the failure was limited to the newly emitted undocumented codes and was corrected.
