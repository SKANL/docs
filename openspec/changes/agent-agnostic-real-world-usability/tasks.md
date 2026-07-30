# Tasks: Agent-Agnostic Real-World Usability

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2000 total across 10 slices (~140-250 each) |
| 400-line budget risk | High (whole change); Low-Medium per slice |
| Chained PRs recommended | Yes |
| Suggested split | 10 slices, PR 1 → PR 10, stacked to main |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Fail-open doctor (E) + toolchain capabilities (L) + minimal `ContentProbePort` | PR 1 | `uv run pytest tests/unit/application/test_doctor.py tests/unit/domain/test_doctor.py -k "manual or strict or capability"` | `uv run python -m docs.cli.main doctor` on a fixture inbox missing a manual | Revert `doctor.py`/`domain/doctor.py` flag flips + delete new port/adapter files |
| 2 | Workspace config file + `doc init` (A) | PR 2 | `uv run pytest tests/unit/domain/test_workspace_config.py tests/unit/cli/test_doc_init.py` | `uv run python -m docs.cli.main doc init` in a scratch dir | Delete `workspace_config.py`, revert `_shared.py:64`, remove `doc init` |
| 3 | Built-in template provisioning (C) | PR 3 | `uv run pytest tests/unit/cli/test_template_app.py -k builtin` | `uv run python -m docs.cli.main template use reporte-estadia-tic` post-`pip install .` | Remove `src/docs/templates/builtin/`, revert `template_app.py`/`pyproject.toml` |
| 4 | Content-probe extension + content classification (D) | PR 4 | `uv run pytest tests/unit/domain/test_source_role.py tests/unit/infrastructure/test_content_probe_adapter.py` | `uv run python -m docs.cli.main pipeline ingest` on a flat-dump fixture | `signals=None` default keeps callers unchanged; revert `ingest.py` wiring only |
| 5 | Wire PDF render adapter into ingest (F) | PR 5 | `uv run pytest tests/unit/application/test_ingest.py -k pdf_render` | `pipeline ingest` on a vector-only PDF fixture | Revert `Deps` wiring + `_build_figure_catalog` gate; adapter file untouched |
| 6 | Figure/table numbering + cross-ref at build (H) | PR 6 | `uv run pytest tests/unit/domain/test_cross_reference.py tests/unit/application/test_docx_assembly.py` | `pipeline assemble` on a fixture with `[[figure:]]`/`[[table:]]`/`[[ref:]]` markers | Remove `cross_reference.py`, revert `docx_assembly.py:100` call site |
| 7 | Evidence-aware review precision (J) | PR 7 | `uv run pytest tests/unit/domain/test_rules.py tests/unit/domain/test_rules_characterization.py` | `uv run python -m docs.cli.main review-section --json` on paired fixtures | Revert `rules.py` predicate changes only; no new files |
| 8 | Cross-source conflict + intake/gap report (G, K) | PR 8 | `uv run pytest tests/unit/domain/test_source_conflict.py tests/unit/domain/test_intake_report.py` | `pipeline ingest` on a fixture with two conflicting sources | Delete `source_conflict.py`/`intake_report.py`, revert ingest call sites |
| 9 | `doc status` (I) | PR 9 | `uv run pytest tests/unit/cli/test_doc_status.py` | `uv run python -m docs.cli.main doc status --json` on a partial document | Remove `doc status` command + aggregator; no shared state touched |
| 10 | Agent contract (`AGENTS.md` + `docs guide`) + reproducibility principle (B, M) | PR 10 | `uv run pytest tests/unit/test_agents_md_packaging.py tests/unit/cli/test_core_app.py -k guide` | `pip install . && docs guide` from an installed wheel | Remove `AGENTS.md`, `docs guide` command, `pyproject.toml` force-include entry |

## Phase 1: Fail-open doctor + toolchain capabilities + minimal ContentProbePort (E, L) — PR 1

- [x] 1.1 RED: `manual_dir` missing → WARN not FAIL (`test_doctor_service.py`)
- [x] 1.2 GREEN: flip `manual_dir` check to `required=False` + next-step detail (`application/doctor.py:29`, `domain/doctor.py:12`)
- [x] 1.3 RED: `--strict` restores hard-fail on optional checks
- [x] 1.4 GREEN: thread `required=strict` for optional checks (`doctor.py`, pattern at `:118,:122`)
- [x] 1.5 RED: probe adapter failure → empty signals, fail-open (locale/platform risk)
- [x] 1.6 GREEN: create `domain/ports/content_probe_port.py` (`ContentSignals`: extension only for now) + `infrastructure/ingest/content_probe_adapter.py` (minimal)
- [x] 1.7 RED: doctor auto-detects manual anywhere under `inbox/` via probe keyword match
- [x] 1.8 GREEN: wire probe into `DoctorService` manual auto-detect, resolved path in WARN detail
- [x] 1.9 RED: pandoc required=True fail; pypdfium2/opendataloader missing → WARN with next-step
- [x] 1.10 GREEN: add capability-checks section to `run_doctor` using `ToolResolverPort` + guarded imports

## Phase 2: Workspace config + `doc init` (A) — PR 2, depends on PR 1

- [x] 2.1 RED: `resolve_workspace_roots` precedence — config overrides env, env overrides default
- [x] 2.2 GREEN: `domain/workspace_config.py:resolve_workspace_roots` (pure)
- [x] 2.3 RED: malformed `docs.config.json` → WARN + fallback, never brick a command
- [x] 2.4 GREEN: `build_workspace()` best-effort reads `Path.cwd()/"docs.config.json"`, delegates to resolver (`cli/_shared.py:64`)
- [x] 2.5 RED: `doc init` bootstraps config+dirs+seeded template; refuses clobber without `--force`
- [x] 2.6 GREEN: implement `doc init` on `doc_app.py:15` (calls `template use` from PR 3 — stub until PR 3 lands, or sequence after PR 3 if simpler)

## Phase 3: Built-in template provisioning (C) — PR 3, depends on PR 2

- [x] 3.1 RED: `template list --available` lists builtin names
- [x] 3.2 GREEN: seed `src/docs/templates/builtin/reporte-estadia-tic.json`, implement `list --available` via `importlib.resources`
- [x] 3.3 RED: `template use <builtin>` copies into `templates_dir`; refuse-clobber w/o `--force`; unknown id errors
- [x] 3.4 GREEN: implement `template use` on `template_app.py:18`
- [x] 3.5 RED: build+install test — builtin template importable from installed wheel (package-data risk)
- [x] 3.6 GREEN: verify/add `pyproject.toml` hatch inclusion for `.json` under `docs.templates.builtin`

## Phase 4: Content classification (D) — PR 4, depends on PR 1 (ContentProbePort)

- [x] 4.1 RED: `classify(path, signals=None)` byte-for-byte unchanged (regression guard)
- [x] 4.2 GREEN: extend `classify()` signature (`domain/source_role.py:51`) with optional weighted content signals
- [x] 4.3 RED: extended probe extracts PDF title/headings/keywords; failure → empty signals (case-folded, ASCII-sorted)
- [x] 4.4 GREEN: extend `content_probe_adapter.py` with PDF/text extraction
- [x] 4.5 RED: high-confidence classification acts automatically; medium/low held to classification queue, never defaulted
- [x] 4.6 GREEN: wire probe output into `IngestService` classify call, inject adapter via `Deps`

## Phase 5: Wire PDF render adapter (F) — PR 5, depends on PR 4

- [x] 5.1 RED: vector-only PDF (no extracted raster) gains rendered-page figures
- [x] 5.2 GREEN: inject optional `pdf_render: PdfRenderPort | None` into `IngestService`, wire `Pdfium2PdfRenderAdapter` in `Deps` (guarded import → `None`)
- [x] 5.3 RED: render toolchain absent → no figures, WARN, document still assembles
- [x] 5.4 GREEN: gate render on empty raster extraction; append `FigureEntry` per page in `_build_figure_catalog` (`ingest.py:735`)
- [x] 5.5 RED: golden byte test — deterministic adapter names + sorted catalog across runs

## Phase 6: Figure/table numbering + cross-ref (H) — PR 6, depends on PR 5

- [x] 6.1 RED: `number_and_resolve` assigns `Figura N`/`Tabla M` in document order, then in-text order
- [x] 6.2 GREEN: implement `domain/cross_reference.py:number_and_resolve` (pure); add `[[table:slug]]` marker
- [x] 6.3 RED: caption rewrite (`Figura N. <caption>`) and `[[ref:slug]]` → `Ver Figura N`/`Ver Tabla M`
- [x] 6.4 GREEN: implement caption/ref rewrite
- [x] 6.5 RED: unresolvable `[[ref:]]` → `Ver Figura ?` + build WARN, never silent
- [x] 6.6 GREEN: add unknown-label handling
- [x] 6.7 RED: reordering sections renumbers deterministically, no manual edits (numbering-determinism risk)
- [x] 6.8 GREEN: wire `number_and_resolve` into `DocxRendererAdapter.build` before `_strip_frontmatter_to_temp`/pandoc (`docx_assembly.py:100`)

## Phase 7: Evidence-aware review precision (J) — PR 7, independent

- [ ] 7.1 RED: paired fixture — delimited "Firebase" w/ evidence NOT flagged; genuinely contested still flagged
- [ ] 7.2 GREEN: local-window evidence predicate in `review_cross_consistency` (`rules.py:574`)
- [ ] 7.3 RED: paired fixture — short keyword no longer matches inside larger word; full keyword still matches
- [ ] 7.4 GREEN: word-boundary match in `requirement_present` (`rules.py:57`)
- [ ] 7.5 RED: paired fixture — subjective term next to citation not flagged; bare term still flagged
- [ ] 7.6 GREEN: evidence-aware suppression in `_check_subjective_terms` (`rules.py:249`)
- [ ] 7.7 Run `test_rules_characterization.py` to confirm no existing catch regresses

## Phase 8: Cross-source conflict + intake/gap report (G, K) — PR 8, depends on PR 5

- [ ] 8.1 RED: `detect_conflicts` flags two sources asserting different members of a mutually-exclusive term group
- [ ] 8.2 GREEN: `domain/source_conflict.py:detect_conflicts` (pure, curated exclusive-group table)
- [ ] 8.3 RED: no conflicts present → empty, deterministic sorted output
- [ ] 8.4 GREEN: wire into `IngestService` post-walk, WARN in manifest
- [ ] 8.5 RED: `render_intake_report` produces Found/Missing/How-to-finish from detection+manifest+gap-report+ledger
- [ ] 8.6 GREEN: `domain/intake_report.py:render_intake_report` (pure); write `inbox/intake-report.md` at end of `ingest_inbox` (`ingest.py:195`)

## Phase 9: `doc status` (I) — PR 9, depends on PR 8

- [ ] 9.1 RED: `doc status --json` reports fresh document context/sections/ingest/figures/output
- [ ] 9.2 GREEN: aggregator reading `ContextService.status`, `gap-report.json`, `figure-catalog.json`, `_detection.json`, `output/` mtimes
- [ ] 9.3 RED: partially completed document shows filled N/M, scaffold sections, queued classifications
- [ ] 9.4 GREEN: wire `doc status [--json]` on `doc_app.py:15`, dual Markdown/JSON output

## Phase 10: Agent contract + reproducibility principle (B, M) — PR 10, depends on all

- [ ] 10.1 RED: characterization test — repo-root `AGENTS.md` bytes equal packaged copy
- [ ] 10.2 GREEN: write `AGENTS.md` (workflow, config/env precedence, `[[figure:]]`/`Ver {ref}` convention, cognitive-slot boundary, reproducibility boundary); force-include in `pyproject.toml`
- [ ] 10.3 RED: `docs guide` works from an installed wheel (no repo checkout)
- [ ] 10.4 GREEN: implement `docs guide` on `core_app.py:17` via `importlib.resources`
- [ ] 10.5 GREEN: add Reproducibility Boundary Principle statement to `openspec/specs/document-pipeline/spec.md` (spec text only)

## Sequencing notes

`ContentProbePort` lands minimal in PR 1 (E's auto-detect) and is extended (not recreated) in PR 4 (D). PR 2's `doc init` calling `template use` (PR 3) means PR 2 and PR 3 may need to land together or PR 2's call site stubbed until PR 3 merges — flag at apply time if stacking order causes a broken intermediate state.
