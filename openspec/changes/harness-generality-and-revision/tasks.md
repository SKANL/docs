# Tasks: Harness Generality & Revision

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1300-1700 total across 7 slices (~130-400 each) |
| 400-line budget risk | Medium overall; Phase 4 (`revise` loop) is High-risk for the cap |
| Chained PRs recommended | Yes |
| Suggested split | 7 slices, PR 1 → PR 7, stacked to main |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Template-driven review rules (A) — backward-compat gated | PR 1 | `uv run pytest tests/unit/domain/test_rules.py tests/unit/domain/test_rules_characterization.py tests/unit/domain/test_normative.py -k "contested or citation_style"` | `uv run python -m docs.cli.main pipeline all --strict` on the estadia fixture doc | Revert `rules.py`/`normative.py`/`review.py` + `reporte-estadia-tic.json` edits; no new files |
| 2 | HTML renderer + `--format` CLI (C-html) | PR 2 | `uv run pytest tests/unit/application/test_html_render.py tests/integration/test_html_determinism.py tests/unit/application/test_renderer_registry.py` | `uv run python -m docs.cli.main pipeline assemble --format html` on a fixture doc | Delete `application/html_render.py`; revert `_shared.py` registration + `core_app.py --format` option |
| 3 | PDF renderer (C-pdf) | PR 3 | `uv run pytest tests/unit/application/test_pdf_render.py tests/integration/test_libreoffice_qa_adapter.py` | `uv run python -m docs.cli.main pipeline assemble --format pdf` with and without soffice on PATH | Delete `application/pdf_render.py`; revert `_shared.py` registration |
| 4 | `doc revise` loop (B) | PR 4 | `uv run pytest tests/unit/application/test_revision.py` | `uv run python -m docs.cli.main doc revise resumen "clarify scope"` on a fixture doc with an authored section | Delete `application/revision.py`; revert `doc_app.py`/`_shared.py` wiring; `sections/_revisions/` left inert |
| 5 | 2nd built-in template + acceptance (D) | PR 5 | `uv run pytest tests/integration/test_technical_report_srs_acceptance.py tests/unit/cli/test_template_app.py -k builtin` | `uv run python -m docs.cli.main template use technical-report-srs` then `pipeline all` | Delete `technical-report-srs.json` + its acceptance test; no shared code touched |
| 6 | Lifecycle + build version + `doc status` (F) | PR 6 | `uv run pytest tests/unit/application/test_status_service.py tests/unit/application/test_pipeline_service.py -k "lifecycle or version"` | `uv run python -m docs.cli.main doc status --json` before/after two `pipeline assemble` runs | Revert `document.py`/`document_status.py`/`status.py`/`pipeline.py` field additions; no new files |
| 7 | AGENTS.md doc coverage (revise/format/lifecycle) | PR 7 | `uv run pytest tests/unit/test_agents_md_packaging.py` | N/A — docs-only; clean-room agent run (E) belongs to verify phase, not apply | Revert added `AGENTS.md` sections |

## Phase 1: Template-driven review rules (A) — PR 1

- [x] 1.1 RED (`tests/unit/domain/test_normative.py`): `NormativeSettings.contested_stack_terms` defaults `[]`; `resolve_normative_settings` reads `config["cross_consistency"]["contested_stack_terms"]`
- [x] 1.2 GREEN: add `contested_stack_terms: list[str]` to `NormativeSettings` (`normative.py:30`), resolve it in `resolve_normative_settings` (`normative.py:46`)
- [x] 1.3 RED (`tests/unit/domain/test_rules.py`): `review_cross_consistency(terms=[])` flags nothing, even for "Laravel" — proves the constant is gone
- [x] 1.4 GREEN: delete `DEFAULT_CONTESTED_STACK_TERMS` (`rules.py:571`) and its fallback (`rules.py:582`)
- [x] 1.5 GREEN: thread `normative.contested_stack_terms` into the `review_cross_consistency` call (`application/review.py:103`)
- [x] 1.6 RED (`tests/unit/domain/test_rules_characterization.py` — compat gate): estadia's 6-term config + unchanged fixture → byte-identical findings pre/post refactor
- [x] 1.7 GREEN: populate `reporte-estadia-tic.json:185` `cross_consistency.contested_stack_terms` with `Laravel, Supabase, bun.js, MySQL, GCP, Firebase`
- [x] 1.8 RED (`tests/unit/domain/test_normative.py`): `citation_style` accepts `apa7`/`none`; other values raise a clear error
- [x] 1.9 GREEN: add `citation_style: str = "apa7"` resolution (`normative.py`/template `apa7` block); `none` forces `apa7.enabled=false`
- [x] 1.10 Run `tests/unit/domain/test_rules_characterization.py` + `tests/integration/test_review_service.py` — confirm estadia byte-identical (hard gate)

## Phase 2: HTML renderer + `--format` CLI (C-html) — PR 2, depends on PR 1

- [ ] 2.1 RED (`tests/unit/application/test_html_render.py`, new): `HtmlRendererAdapter.output_format == "html"`; `build()` invokes pandoc, returns the output path
- [ ] 2.2 GREEN: create `application/html_render.py:HtmlRendererAdapter` (reuse the numbering/frontmatter-strip pass from `docx_assembly.py:_strip_frontmatter_to_temp`; `subprocess.run([pandoc, *inputs, "--standalone", "--embed-resources", "-o", output])`)
- [ ] 2.3 RED (`tests/integration/test_html_determinism.py`, new): building unchanged sections twice produces byte-identical `.html`
- [ ] 2.4 GREEN: strip any pandoc-injected date/generator metadata that breaks determinism
- [ ] 2.5 RED (`tests/unit/cli/test_core_app.py`, new): `pipeline assemble --format html` selects the html renderer; repeatable `--format` builds several; no flag keeps today's docx-only behavior
- [ ] 2.6 GREEN: add repeatable `--format` Option to `core_app.pipeline` (`core_app.py:58`), loop `resolve_renderer` + `run_pipeline` per requested format (default `["docx"]`)
- [ ] 2.7 GREEN: register `Deps.renderers["html"]` (`cli/_shared.py:119`)
- [ ] 2.8 Run `tests/unit/application/test_renderer_registry.py` + `tests/integration/test_docx_assembly_service.py` — confirm default docx-only path unaffected

## Phase 3: PDF renderer (C-pdf) — PR 3, depends on PR 2

- [ ] 3.1 RED (`tests/unit/application/test_pdf_render.py`, new): `PdfRendererAdapter.output_format == "pdf"`; `build()` builds the docx then calls `render_docx_to_pdf`
- [ ] 3.2 GREEN: create `application/pdf_render.py:PdfRendererAdapter` (wraps `DocxRendererAdapter` + `QaRenderPort.render_docx_to_pdf`)
- [ ] 3.3 RED: soffice absent (`resolve_libreoffice_executable` → `None`) → WARN + skip PDF; other requested formats still build (threat-matrix: missing-toolchain degradation)
- [ ] 3.4 GREEN: catch the missing-toolchain `RuntimeError` in `PdfRendererAdapter.build`, print a WARN, skip (return `None`); `core_app.pipeline`'s format loop skips `None` results
- [ ] 3.5 GREEN: register `Deps.renderers["pdf"]` (`cli/_shared.py:119`)
- [ ] 3.6 Run `tests/integration/test_libreoffice_qa_adapter.py` — confirm the shared `render_docx_to_pdf` path is unaffected

## Phase 4: `doc revise` loop (B) — PR 4, independent of PR 2/3

- [ ] 4.1 RED (`tests/unit/application/test_revision.py`, new): `RevisionService.revise(doc_id, template, config, section_id, new_body, request)` returns before/after Markdown + a one-line summary
- [ ] 4.2 GREEN: create `application/revision.py:RevisionService` (`SectionRepository`, `ReviewService`, `ContextService`); snapshots pre-edit body to `sections/_revisions/NNN-<id>.<n>.md`, writes new body, diffs with `difflib.unified_diff`
- [ ] 4.3 RED: only the edited section + `review-document` are re-validated; other sections' `review_section` is not invoked
- [ ] 4.4 GREEN: scope `revise()`'s re-validation call to the edited section id + `review_document`
- [ ] 4.5 RED: a successful revise appends one entry (`request`, `section_id`, `diff_path`, `before_hash`, `after_hash`, `ts`) to `sections/_revisions/revision-log.json`; prior entries stay, in order
- [ ] 4.6 GREEN: implement append-only read-modify-write for `revision-log.json` (`schema: 1, entries: []`)
- [ ] 4.7 RED: a `context` topic edit ripples via `Topic.consumed_by` (`template.py:20`) to dependent sections; non-dependent sections stay untouched
- [ ] 4.8 GREEN: `RevisionService.revise_topic(doc_id, template, config, topic_id, new_value, request)` — writes via `ContextService.set`, maps `consumed_by` → dependent section ids, re-validates each + `review-document`, logs `ripple: [...]`
- [ ] 4.9 RED: a structural request (unknown section/topic id, or explicit add/remove) is rejected naming `revise` as unsuited for structural changes
- [ ] 4.10 GREEN: validate the target id against `template.sections`/`context_schema.topics` before proceeding; raise `ValueError` with that message
- [ ] 4.11 RED (`tests/integration/test_corrections_service.py`, regression): `apply-corrections` still produces no diff/provenance/log entry after this change
- [ ] 4.12 GREEN: confirm `CorrectionsService.apply_corrections` shares no code path with `RevisionService` (isolation check; no code change expected)
- [ ] 4.13 GREEN (CLI wiring): add `doc revise <section-or-topic-id> "<request>"` to `cli/commands/doc_app.py`; wire `Deps.revision = RevisionService(...)` (`cli/_shared.py`)
- [ ] 4.14 Run `tests/unit/application/test_revision.py` + `tests/integration/test_review_service.py` — confirm no regression to existing review call sites

## Phase 5: 2nd built-in template + acceptance (D) — PR 5, depends on PR 1

- [ ] 5.1 RED (`tests/integration/test_technical_report_srs_acceptance.py`, new): full pipeline (ingest → author → review → assemble) on the SRS template completes green, using ITS `contested_stack_terms`/`citation_style: none` — not estadia's
- [ ] 5.2 GREEN: author `templates/builtin/technical-report-srs.json` (English, non-APA, `citation_style: none`, distinct `subjective_terms`/`contested_stack_terms`, structurally different sections)
- [ ] 5.3 RED (`tests/unit/cli/test_template_app.py`, extend): `template list --available` lists both `reporte-estadia-tic` and `technical-report-srs`; both usable via `template use`
- [ ] 5.4 GREEN: verify `pyproject.toml`'s existing `templates/builtin/*.json` package-data glob already covers the new file (no change expected)
- [ ] 5.5 Run `tests/integration/test_documento_generico_acceptance.py` + the new SRS acceptance test together — proves A's config-drive across two independent templates

## Phase 6: Lifecycle + build version + `doc status` (F) — PR 6, independent

- [ ] 6.1 RED (`tests/unit/application/test_pipeline_service.py`, extend): first `run_pipeline`/assemble records build version `1`; a repeated run increments to `N + 1`
- [ ] 6.2 GREEN: track build version from `runs/` (existing wall-clock log) or a small counter file; increment in `PipelineService.log_run`/`stage_build_docx`
- [ ] 6.3 RED (`tests/unit/application/test_documents.py`, extend): `Document` defaults `lifecycle="draft"`; an explicit mark sets `"final"`
- [ ] 6.4 GREEN: add `lifecycle: str = "draft"` to `Document` (`domain/models/document.py:8`); add a `DocumentService.mark_final`/`doc mark-final <id>` write path
- [ ] 6.5 RED (`tests/unit/application/test_status_service.py`, extend): `doc status` reports `lifecycle` + latest `build_version`; pre-assemble shows `draft` + no version
- [ ] 6.6 GREEN: extend `DocumentStatus` (`domain/document_status.py:9`) with `lifecycle`/`build_version`; `StatusService.status_summary` reads `Document.lifecycle` + latest `runs/` version
- [ ] 6.7 Run `tests/unit/application/test_status_service.py` + `tests/unit/application/test_pipeline_service.py` — regression check

## Phase 7: AGENTS.md documentation coverage — PR 7, depends on PR 3, PR 4, PR 6

- [ ] 7.1 GREEN: amend `AGENTS.md` §5 — PDF explicitly non-byte-deterministic + WARN+skip caveat; document `--format html/pdf` selection
- [ ] 7.2 GREEN: document the `doc revise <section|topic> "<request>"` loop (diff + scoped re-validation + provenance) in `AGENTS.md`
- [ ] 7.3 GREEN: document `doc status`'s lifecycle/build-version fields in `AGENTS.md`
- [ ] 7.4 Run `tests/unit/test_agents_md_packaging.py` — confirm repo-root/packaged-copy bytes stay in sync

## Verify-phase note (E, not an apply task)

Clean-room verification (agent-contract "Clean-Room Verification Drives AGENTS.md
Refinement") runs in `sdd-verify`: an agent given only `AGENTS.md` + arbitrary raw
files (no source/tests access) attempts the full workflow end-to-end, including
`doc revise`, `--format` selection, and `doc status` lifecycle/version. Any step
it gets stuck on is a gap closed by an additive `AGENTS.md` edit, then re-run
until it completes unaided.

## Sequencing notes

Phase 1 gates Phase 5 (SRS template proves A's config-drive) — PR 5 must land
after PR 1. Phase 2 (HTML + `--format` CLI) gates Phase 3 (PDF reuses the same
CLI loop). Phase 4 (`revise`) and Phase 6 (lifecycle) are independent of 2/3/5
and each other — may reorder if PR 4's estimated size runs over budget; split
into B1 (prose revise, 4.1-4.6, 4.9-4.14) / B2 (topic ripple, 4.7-4.8) if so.
Phase 7 depends on 3, 4, and 6 landing (documents all three).
