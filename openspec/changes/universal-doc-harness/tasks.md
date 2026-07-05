# Tasks: universal-doc-harness

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,250 total across 8 slices (~200-340 each) |
| 400-line budget risk | High (single PR) / Low-Medium (per slice) |
| Chained PRs recommended | Yes |
| Suggested split | PR1 -> PR2 -> PR3 -> PR4 -> PR5 -> PR6 -> PR7 -> PR8 |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low-Medium (per slice); High if collapsed to one PR

### Suggested Work Units (all target `main`, merge in order, main stays green after each)

| Unit | Goal | PR | Est. lines | Depends on |
|------|------|----|-----------:|------------|
| 1 | Sentinel rename + asset-kind generalization + quick debt (deps, except-fix) | PR1 | ~220 | none |
| 2 | Repository port segregation (ISP) | PR2 | ~260 | PR1 |
| 3 | CLI composition root split | PR3 | ~320 | PR2 |
| 4 | Renderer registry + data-driven stage plan | PR4 | ~300 | PR3 |
| 5 | opendataloader-pdf verification + ingest detect/route infra | PR5 | ~260 | PR4 |
| 6 | Ingest per-type adapters (pandoc, PDF, md/txt) | PR6 | ~340 | PR5 |
| 7 | Context files + progressive-disclosure index | PR7 | ~300 | PR6 |
| 8 | Pipeline wiring + app-layer test/debt closeout | PR8 | ~250 | PR7 |

Strict TDD is active (`uv run pytest`): every implementation task is preceded by its RED (failing test) task.

---

## PR1 — Sentinel Rename + Asset Generalization (Foundation)
Base: `main`. Covers: document-pipeline (`No hardcoded format identifiers remain`, deps/error-handling reqs), asset-management (both requirements).

- [x] 1.1 RED: add/adjust tests in `tests/unit/domain/test_evidence.py`, `test_collection.py`, `test_rules.py`, `test_sections.py`, `test_review.py`, `test_section_rendering.py` asserting no `"tesina"` literal remains.
- [x] 1.2 GREEN: remove `"tesina"` sentinel identifiers from `domain/evidence.py`, `collection.py`, `rules.py`, `sections.py`, `review.py`, `section_rendering.py`; keep `managed_by` gate semantics, atomic single-slice rename.
- [x] 1.3 RED: `tests/unit/infrastructure/test_filesystem_asset_repository.py` — asset-kind allow/reject scenarios (docx-only config still rejects non-docx).
- [x] 1.4 GREEN: `domain/ports/asset_repository.py` add `list_assets(directory, kind)` replacing `glob_docx`; `application/asset.py` validate by configurable asset-kind map.
- [x] 1.5 GREEN: `infrastructure/persistence/filesystem_asset_repository.py` implement kind-agnostic listing.
- [x] 1.6 GREEN: `pyproject.toml` — declare `docxcompose`, `filetype`, `opendataloader-pdf`.
- [x] 1.7 RED: `tests/unit/infrastructure/test_filesystem_source_repository.py` — git-helper failure surfaced (logged/raised), not swallowed.
- [x] 1.8 GREEN: `infrastructure/persistence/filesystem_source_repository.py` — replace silent `except Exception` with logged/re-raised error.
- [x] 1.9 Verify: `uv run pytest` green; grep confirms zero `"tesina"` literals in `src/docs/` domain layer swept by 1.1-1.2 (`evidence.py`, `collection.py`, `rules.py`, `sections.py`, `review.py`, `section_rendering.py`) plus the coupled `application/review.py` managed_by gate. `application/docx_assembly.py`'s `tesina-draft.docx`/`tesina-body.docx`, `application/pipeline.py`'s `_DRAFT_DOCX_NAME`, and `application/collection.py`'s `"tesina/context"` tag remain — they are explicitly owned by PR4/PR8 per design.md's file-changes table and are out of scope for this slice.
- [x] 1.10 Rollback: revert PR1 commit range; no data migration, no downstream dependents yet.

## PR2 — Repository Port Segregation (ISP)
Base: `main` (after PR1). Covers: document-pipeline (`Repository Port Segregation`).

- [x] 2.1 RED: `tests/unit/domain` — new tests asserting narrow ports (`RegistryRepository.active_id`, `DocumentRepository.read_document`, `TemplateRepository.load_template`) each usable independently.
- [x] 2.2 GREEN: split `domain/ports/document_repository.py` into `registry_repository.py`, `document_repository.py`, `template_repository.py`.
- [x] 2.3 GREEN: update `infrastructure/persistence/json_repository.py` to implement all three narrow ports on one adapter class.
- [x] 2.4 GREEN: update consumers (`application/documents.py`, `docx_assembly.py`, `context_pack.py`, others importing the old fat port) to depend on the narrow port they use. Verified via grep + CodeGraph blast-radius: the only actual importers of the fat port are `application/documents.py` and `application/context.py`; `docx_assembly.py`/`context_pack.py` never imported `DocumentRepository` (design.md's generic mention did not match current code). `context.py` needed zero changes — it already only calls `.exists()`, satisfied by the narrow `DocumentRepository`. `DocumentService` (documents.py) genuinely spans all three ports (registry+content+template), so it depends on a locally-defined `DocumentLifecycleRepository(RegistryRepository, DocumentRepository, TemplateRepository, Protocol)` composed type instead of reintroducing one fat protocol — zero call-site changes needed in `cli/_shared.py` or existing tests.
- [x] 2.5 Verify: `uv run pytest` green (existing `tests/integration/test_json_repository.py`, `test_document_service.py` unchanged behavior). Full suite: 790 passed, 7 skipped (787 baseline + 3 new port-segregation tests).
- [x] 2.6 Rollback: revert PR2; PR1 unaffected since it has no port dependency.

## PR3 — CLI Composition Root Split
Base: `main` (after PR2). Covers: document-pipeline (`CLI Composition Root Segregation`).

- [x] 3.1 RED: `tests/integration/test_cli_core.py` (+ existing `test_cli_collection/docx/template/doc/asset/context/section.py`) — assert each command still reachable post-split. DEVIATION: `test_cli_core.py` already existed pre-PR3 (written in an earlier characterization pass); it passed against the still-monolithic `main.py` and is not a valid RED anchor by itself. Added new `tests/integration/test_cli_composition_root.py` as the genuine RED for this slice — asserts (a) each `cli/commands/*_app.py` module exists and exposes the expected command set, and (b) the root app's flattened command tree is byte-identical to the pre-split snapshot. Confirmed RED (`ModuleNotFoundError: docs.cli.commands`) before 3.2.
- [x] 3.2 GREEN: split `cli/main.py` into `cli/commands/*_app.py` sub-Typer apps by concern (core, collection, docx, section, template, doc, asset, context). DEVIATION: no `ingest` placeholder module added — there are zero ingest commands in the current CLI to place, and PR5/PR6 own that port/adapter/wiring; adding an unmounted, untested stub file would be speculative dead code out of this slice's scope. `core`/`collection`/`docx`/`section` are new organizational modules (no group prefix existed for them) mounted via `app.add_typer(sub_app)` **without** a `name` — verified empirically that Typer/Click flattens an unnamed sub-Typer's commands onto the parent Group (no prefix), preserving the exact flat command surface. `template`/`doc`/`asset`/`context` keep their existing group names unchanged. Added a small `_ctx(ctx)` helper to `cli/_shared.py` (moved from `main.py`) so all command modules share one implementation without a `main.py` <-> `commands.*` import cycle.
- [x] 3.3 GREEN: delete root `main.py` (dead entrypoint). Verified via `codegraph explore` + repo-wide grep: no import of root `main.py` exists anywhere (pyproject.toml's `[project.scripts]` points at `docs.cli.main:main`, i.e. `src/docs/cli/main.py`, not the root file); root `main.py` only contained a placeholder `print("Hello from docs!")`.
- [x] 3.4 Verify: `uv run pytest` green (793 passed, 7 skipped — baseline 790 passed/7 skipped + 3 new composition-root tests); `python -m docs.cli.main --help` captured before and after the split and diffed byte-for-byte identical.
- [x] 3.5 Rollback: revert PR3; CLI entrypoint reassembled from sub-apps, no state impact. Confirmed: reverting restores the single monolithic `cli/main.py` + dead root `main.py`, no data/document state touched by this slice.

## PR4 — Renderer Registry + Data-Driven Stage Plan
Base: `main` (after PR3). Covers: document-render (all 4 requirements), document-pipeline (`Data-Driven, Format-Agnostic Stage Plan`).

- [ ] 4.1 RED: `tests/unit/domain/test_pipeline.py` — `pipeline_stage_plan(stage_set, ...)` rejects unknown stage_set; same stage_set+format called twice returns identical ordered list (determinism).
- [ ] 4.2 GREEN: create `domain/ports/document_renderer_port.py` (`DocumentRendererPort`: `output_format`, `stage_plan()`, `build()`).
- [ ] 4.3 GREEN: rewrite `domain/pipeline.py:pipeline_stage_plan` to accept stage-name tuples from the resolved renderer — zero format literals.
- [ ] 4.4 RED: `tests/integration/test_docx_assembly_service.py` extended — DOCX renderer resolves via registry, config-driven `tesina-draft.docx`/`tesina-body.docx` names become config values.
- [ ] 4.5 GREEN: rename `application/docx_assembly.py` service to `DocxRendererAdapter` behind `DocumentRendererPort`; move hardcoded doc names into `config["output"]`.
- [ ] 4.6 GREEN: `cli/_shared.py` — add `RENDERERS: dict[str, DocumentRendererPort]` map, resolve by `config["output"]["format"]` (default `"docx"`); raise clear error on unregistered format (no silent DOCX fallback).
- [ ] 4.7 RED: new `tests/unit/application/test_renderer_registry.py` — register test-only fake `"txt"` renderer; pipeline resolves and builds via the fake with zero edits to `domain/pipeline.py`.
- [ ] 4.8 GREEN: implement the fake-renderer test fixture proving extensibility (test-only, not shipped).
- [ ] 4.9 Verify: `uv run pytest` green; DOCX regression suite (`test_docx_assembly_service.py`) unchanged; run pipeline twice, confirm identical stage-plan output (determinism).
- [ ] 4.10 Rollback: revert PR4; registry is additive — reverting restores DOCX-only hardcoded path from PR3 baseline.

## PR5 — opendataloader-pdf Verification + Ingest Detection/Routing Infra
Base: `main` (after PR4). Covers: document-ingest (`File-Type Detection`, `Type-Based Ingest Routing` routing only, `Empty inbox` scenario).

- [ ] 5.1 Spike (non-code, blocking gate): verify `opendataloader-pdf` maturity/license/API stability — record findings in PR description; MUST complete and pass before 5.6/6.x lock the dependency in code.
- [ ] 5.2 RED: `tests/unit/infrastructure/test_source_type_detector.py` — magic-byte detection for pdf/docx, extension fallback for md/txt, unknown-type returns `""`.
- [ ] 5.3 GREEN: create `domain/ports/source_type_detector_port.py` (`SourceTypeDetectorPort.detect`); `infrastructure/ingest/filetype_detector_adapter.py` using `filetype` lib + extension fallback.
- [ ] 5.4 RED: `tests/unit/application/test_ingest_service.py` — router maps detected kind to handler stub; unsupported type recorded as `status: "unsupported"`, never raises; empty inbox → zero files processed, no error.
- [ ] 5.5 GREEN: create `domain/ports/source_ingest_port.py` (`SourceIngestPort.ingest`); `application/ingest.py` `IngestService` (detect -> route -> ingest, writes `inbox/_detection.json`).
- [ ] 5.6 GREEN: idempotency — compute sha256 of source, derive `sha8`; skip re-ingest when `sections/ingested/<stem>-<sha8>.md` already recorded with matching hash.
- [ ] 5.7 Verify: `uv run pytest` green; routing/detection tests pass with stub adapters (no real pandoc/opendataloader calls yet).
- [ ] 5.8 Rollback: revert PR5; no adapters wired into `application/pipeline.py` yet, zero blast radius.

## PR6 — Ingest Per-Type Adapters
Base: `main` (after PR5, gated on 5.1 verification passing). Covers: document-ingest (`Type-Based Ingest Routing`, `Deterministic and Idempotent Ingest`, `Tool-Failure Reporting`).

- [ ] 6.1 RED: `tests/integration/test_pandoc_ingest_adapter.py` — DOCX/ODT source -> pandoc `--extract-media` -> markdown + per-doc media dir; missing pandoc reports clear error via `ToolResolverPort`, no partial output.
- [ ] 6.2 GREEN: `infrastructure/ingest/pandoc_ingest_adapter.py` implementing `SourceIngestPort` for docx/odt.
- [ ] 6.3 RED: `tests/integration/test_opendataloader_pdf_adapter.py` — PDF -> markdown; conversion failure reports cause per-file and applies configured fail-fast.
- [ ] 6.4 GREEN: `infrastructure/ingest/opendataloader_pdf_adapter.py` implementing `SourceIngestPort` for pdf (only after 5.1 sign-off).
- [ ] 6.5 RED: `tests/unit/infrastructure/test_md_normalize_adapter.py` — md/txt frontmatter normalization, reuse `split_frontmatter`.
- [ ] 6.6 GREEN: `infrastructure/ingest/md_normalize_adapter.py` implementing `SourceIngestPort` for md/txt.
- [ ] 6.7 GREEN: wire all three adapters into `IngestService` routing table (`application/ingest.py`) and `cli/_shared.py` registration.
- [ ] 6.8 Test — Determinism: `tests/integration/test_ingest_determinism.py` — run ingest twice over the same inbox fixture, assert byte-identical `.md` output and unchanged behavior on partially-processed inbox (no duplication/corruption).
- [ ] 6.9 Verify: `uv run pytest` green including new integration adapters (pandoc/opendataloader-pdf test-doubled or skipped if tool unavailable in CI, per existing `ToolResolverPort` pattern).
- [ ] 6.10 Rollback: revert PR6; PR5 routing infra still functions with adapters absent (falls back to `"unsupported"` reporting).

## PR7 — Context Files + Progressive-Disclosure Index
Base: `main` (after PR6). Covers: context-curation (all 4 requirements).

- [ ] 7.1 RED: `tests/unit/application/test_context_files.py` — skeleton generation produces deterministic headings/instructions + explicit empty `AGENT-FILL` block per concern (keywords/tone/structure/writing-style/formatting-rules).
- [ ] 7.2 GREEN: create `application/context_files.py` — pure functions building skeletons from ingested markdown.
- [ ] 7.3 RED: test — re-running skeleton generation over a file with existing `AGENT-FILL` content does not overwrite/discard it (idempotent merge).
- [ ] 7.4 GREEN: implement idempotent merge preserving `AGENT-FILL` blocks on regeneration.
- [ ] 7.5 RED: `tests/unit/application/test_context_index.py` — exactly one `index.md` generated, 3-level structure (overview, per-file summary with links, references pointer), reuses `read_context_texts` skip rules (`index.md`, `_`-prefixed).
- [ ] 7.6 GREEN: implement index builder in `application/context_files.py`; replace JSON-only `context/index.json` with markdown `context/index.md`.
- [ ] 7.7 Test — Determinism: same ingested sources + config run twice -> identical file set and skeleton structure per file (`tests/unit/application/test_context_files.py::test_same_inputs_same_output`).
- [ ] 7.8 Test — No auto-invoke: assert context-curation completion triggers no agent process call.
- [ ] 7.9 Verify: `uv run pytest` green.
- [ ] 7.10 Rollback: revert PR7; ingest pipeline (PR5/PR6) unaffected since context stage is additive.

## PR8 — Pipeline Wiring + App-Layer Test/Debt Closeout
Base: `main` (after PR7). Covers: document-pipeline (`Application-Layer Test Coverage and Index De-duplication`), proposal success criterion (full pipeline reproducibility).

- [ ] 8.1 GREEN: `application/pipeline.py` — add `ingest` and `build-context-files`/`build-context-index` stage callables to the `ingest` stage_set; drop `_DRAFT_DOCX_NAME` literal (superseded by PR4 config).
- [ ] 8.2 RED: identify application services lacking unit tests (pipeline, asset, ingest, context) via `uv run pytest --collect-only`; write missing unit tests per service.
- [ ] 8.3 GREEN: close test gaps found in 8.2 (one passing unit test per uncovered application service).
- [ ] 8.4 RED: `tests/unit/domain/test_sections.py` (or shared module) — assert exactly one `_sections_index` implementation is exercised by all former call sites.
- [ ] 8.5 GREEN: de-duplicate `_sections_index` into a single shared implementation; update all call sites.
- [ ] 8.6 Test — Full-pipeline determinism: `tests/integration/test_pipeline_service.py` extension — run `ingest` -> `build-context-files` -> `assemble` twice on the same fixture inbox/config; assert identical outputs end-to-end (proposal success criterion).
- [ ] 8.7 Verify: `uv run pytest` full suite green; grep confirms no remaining `"tesina"` or dead `main.py`.
- [ ] 8.8 Rollback: revert PR8; wiring is additive on top of PR4-PR7, DOCX-only path still reachable via existing stage_set `assemble`.

---

## Notes

- Determinism verification tasks: 4.9 (stage plan), 6.8 (ingest byte-identical), 7.7 (context skeleton set), 8.6 (full pipeline, double-run).
- Extensibility proof: 4.7-4.8 (fake `"txt"` renderer, no `domain/pipeline.py` edits).
- Gate: 5.1 (opendataloader-pdf verification) MUST pass before 5.6 (hash/lock groundwork) and PR6 tasks 6.3-6.4 (real PDF adapter) proceed.
- Each PR is independently revertible; stacked-to-main means every merge must leave `main` green — do not merge a slice with failing `uv run pytest`.
