# Verify Report: harness-generality-and-revision

**Branch**: `feat/harness-generality` (PR #22, open, unmerged — 7 commits ahead
of `main`, local HEAD == `origin/feat/harness-generality`, working tree clean
except unrelated `.atl/` cache files).

## Test Suite

`uv run pytest` (full suite): **1300 passed, 0 failed, 7 skipped**.

Targeted re-runs (isolation double-check):
- `test_rules_characterization.py` + `test_technical_report_srs_acceptance.py`
  + `test_documento_generico_acceptance.py` + `test_html_determinism.py`: 16
  passed.
- `test_review_service.py` (estadia review regression, task 1.10's hard
  gate): 25 passed.

`ruff check .`: 8 pre-existing violations (E402/F401/F841), all in
`tests/unit/domain/test_rules.py` and 6 other files. Confirmed against `main`:
identical violation count/lines pre-exist on `main` (checked out both files
from `main`, re-ran ruff — same 8 issues). Not introduced by this change.

## Per-Item Findings

**A — Template-driven rules**: SATISFIED. `DEFAULT_CONTESTED_STACK_TERMS`
removed from `domain/rules.py`; `NormativeSettings.contested_stack_terms` +
`citation_style` (`domain/normative.py`) threaded through
`review_cross_consistency` (`application/review.py`). Estadia declares its 6
terms in `templates/builtin/reporte-estadia-tic.json`. Characterization +
review-service regression green.

**B — `doc revise`**: SATISFIED. All 8 `document-revise` spec scenarios map
to checked tasks (4.1-4.14): prose diff, topic diff, scoped re-validation,
ripple via `Topic.consumed_by`, append-only `revision-log.json` provenance,
history accumulation, structural-edit rejection, `apply-corrections`
isolation (confirmed by code inspection — no shared import). CLI wired:
`doc revise <id> <request> <archivo> [--field] [--strict] [--json]` (`--help`
verified live).

**C — HTML/PDF renderers**: SATISFIED. `HtmlRendererAdapter` byte-determinism
proven by `test_html_determinism.py` (pandoc 3.10, only injected metadata is
the version string, no wall-clock). `PdfRendererAdapter` WARN+skip on missing
soffice, other formats still build (tasks 3.3/3.4). `pipeline --format` is
repeatable, default `docx` (verified via live `--help`).

**D — 2nd built-in template**: SATISFIED. `template list --available` (live
run) lists `documento-generico`, `reporte-estadia-tic`,
`technical-report-srs`. `test_technical_report_srs_acceptance.py` builds the
full ingest→author→review→assemble pipeline on it, green, using its own
distinct `citation_style: none` + contested-term config — proves A's
config-drive generalizes to a non-APA template.

**F — Lifecycle + build version**: SATISFIED. `Document.lifecycle` defaults
`"draft"`; `doc mark-final [<id>]` live `--help` confirmed. `build_version`
increments from `runs/` scan, surfaced by `doc status --json`. Guide text
documents both with a JSON example.

**E — AGENTS.md documents the new surface**: SATISFIED for static content
coverage. Live `guide` output (grepped) confirms `--format html|pdf|docx`,
`doc revise` (step 13 + full §5), `doc mark-final` (step 14 + §6
lifecycle/build_version), and `technical-report-srs` are all present with
concrete example commands. `tests/unit/test_agents_md_content.py` (4 tests)
and `tests/unit/test_agents_md_packaging.py` (repo-root/wheel byte-sync) both
pass.

## Issues Found

**WARNING** — The `agent-contract` spec's own added requirement,
"Clean-Room Verification Drives AGENTS.md Refinement," specifies a literal
dynamic scenario: *an agent with only `AGENTS.md` and raw files, no
source/tests access, attempts the full workflow end-to-end*. What actually
ran this session is a static proxy (automated keyword-presence test +
this verifier's own `guide`-output grep), not an independent agent
role-play with zero codebase access. The content is demonstrably present and
commands are copy-pasteable, so the functional risk is low, but the spec's
own MUST scenario ("clean-room agent completes the full workflow using only
documented commands") has not been literally executed and recorded anywhere
in this change's artifacts. Recommend either (a) running one true clean-room
sub-agent pass before archive, closing any gap found, or (b) explicitly
accepting the static content-check + smoke-test as the change's chosen
lighter-weight substitute and noting that decision in the archive report.
Non-blocking for archive given zero CRITICAL findings elsewhere, but flagged
so the decision is explicit rather than silently skipped.

**SUGGESTION** — `state.yaml` for this change still shows `apply: pending` /
`verify: pending` despite all 7 apply-phase PRs being merged into the branch
and `tasks.md` fully checked; only `propose`/`spec`/`design`/`tasks` phases
were ever written back to the file (single commit `40f0482`, at change
creation). This verify pass updates `state.yaml` to close that drift; future
apply sessions should write phase status back to `state.yaml` at the end of
each PR/slice, not only to `tasks.md`.

## Summary

0 CRITICAL, 1 WARNING (clean-room scenario ran as static proxy, not literal
dynamic agent role-play), 1 SUGGESTION (state.yaml phase-tracking drift,
fixed by this verify pass). All 54 tasks in `tasks.md` are `[x]` and match
the code on `feat/harness-generality`. Full test suite green (1300/0/7).
Branch is NOT yet merged to `main` (PR #22 open). Recommend `sdd-archive`
once the maintainer either runs the clean-room pass or explicitly accepts the
static substitute, and once PR #22 is merged.
