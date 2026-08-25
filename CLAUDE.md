# docs — document-creation harness

Format-agnostic, deterministic document-creation harness (hexagonal
architecture). The harness does all mechanical work; the AI model only fills
structured cognitive slots. The founding refactor (SDD change
`universal-doc-harness`, 10 PRs) is complete and archived; the capability
contract now lives in `openspec/specs/`.

## Commands

- Test: `uv run pytest` (strict TDD — write the failing test first, always)
- Run CLI: `uv run python -m docs.cli.main --help`
- Pipeline stage sets: `pipeline <prep|ingest|assemble|all>` — `ingest` must
  run before `assemble`/`all` when sources exist in `inbox/` (`all` does NOT
  include ingest stages, by design).
- Lint/typecheck: `uv run ruff check .` / `uv run mypy` — both DECLARED in
  `[dependency-groups] dev`, with their rulesets declared in
  `pyproject.toml`. Keep the `uv run` prefix: an undeclared tool falls
  through to whatever is on PATH under a different interpreter that cannot
  see the project's dependencies, which is how `mypy` once reported ~19
  phantom `import-not-found` errors and `coverage` failed collection
  outright. Both are green; CI keeps them that way.
- Coverage: `uv run pytest --cov=src` (96%; CI floor is 93%).

## Layout

- `src/docs/domain/` — pure logic + `ports/` (typing.Protocol interfaces)
- `src/docs/application/` — services, depend on ports only
- `src/docs/infrastructure/` — adapters (filesystem, python-docx, pandoc)
- `src/docs/cli/` — Typer CLI; composition root in `cli/_shared.py` (Deps)
- `tests/unit/`, `tests/integration/` — mirror the src layers
- `tests/architecture/` — repo-wide invariants (see "Mechanised invariants")

Ingest is three modules, not one: `application/ingest.py` (`IngestService`:
detection, conversion, reporting), `ingest_classification.py`
(`SourceClassifier`: role gating, near-duplicates, conflicts),
`ingest_figures.py` (`FigureIngestPipeline`: asset routing, figure catalog,
rasterization — it owns `ImageMetadataPort`/`PdfRenderPort`/
`SvgRasterizerPort` exclusively). `ingest_names.py` holds the vocabulary all
three share; never re-declare an artifact filename or extension set locally.

## Conventions

- Dependency direction: cli → application → domain; infrastructure implements
  domain ports. Never import infrastructure from domain/application.
- Adapters are wired only in the composition root (`cli/_shared.py`).
- CLI user-facing strings are Spanish; code, comments, and docs are English.
- A `# ponytail:` comment marks a deliberate simplification and names its
  ceiling plus the upgrade path, so a shortcut reads as intent rather than
  oversight. Used across `src/`, `tests/` and `tools/`.
- Determinism: same inputs must produce identical outputs; no timestamps or
  randomness in generated artifacts.

## Determinism & collision gotchas (learned the hard way)

- **A declared path may exist under a different Unicode form.** OneDrive
  stores an accented filename decomposed (NFD: `I` + combining acute) while a
  template declares it composed (NFC: `Í`) — the same name to a human,
  different strings to `Path.exists()`. In a Spanish-first harness that is
  the norm, not an edge case. `domain/doctor.py:match_normalized` owns the
  comparison; the caller lists the directory.
- **"Found" is not "usable", and this repo has learned it four times:**
  `safe_style_name` (listed ≠ applicable), `MermaidSvgRenderer` (present ≠
  renders), `doctor`'s toolchain checks (on PATH ≠ new enough), and
  `ContentSignals.container_ok` (exists ≠ actually a `.docx`). Before adding
  a check that a thing is THERE, ask what would make it unusable and check
  that instead.

- Any new `.docx`/zip writer MUST end in
  `infrastructure/docx/deterministic_zip.py:normalize_docx_zip_timestamps` —
  stdlib zip stamps wall-clock entry times at 2s DOS granularity, so a
  "flaky" byte-identity test is a product bug, not test noise. This is now
  MECHANICAL: `tests/architecture/test_docx_writer_invariant.py` fails on any
  module that writes a zip or saves a python-docx document without routing
  through the normalizer. It needs no graph index, so it never skips.
- Never truthiness-test an `ElementTree.Element`. `Element.__bool__` means
  "has children" (deprecated in 3.12, an error later), so `if not
  root.find(x)` reads a present-but-childless element as absent — that
  shipped a duplicate `<w:num>` definition into `numbering.xml`. Always
  `find(...) is None`.
- Any new reader or writer of `context/` MUST use
  `domain/context_index_files.py:is_context_content_filename` — never
  re-declare index/`_`-prefix skip rules locally (a writer-side rename once
  leaked the curated index into the evidence pipeline via the readers).
- Generated indexes: Topic/Q&A owns `context/index.md`; context curation
  owns `context/curated-index.md`. Do not consolidate or re-target.
- `SourceIngestPort.ingest(src, out_dir, kind)` — kind comes from the
  detector/router, never re-derive it from `src.suffix`.
- Ingest output identity: `<stem>-<kind>-<sha8>.md` via
  `domain/ingest_naming.py`; adapters write temp-then-atomic-rename
  (`infrastructure/ingest/atomic_ingest_write.py`) so failures never leave
  a partial file the skip-check would accept.

## Specs & planning — read on demand (do not @import)

- `openspec/specs/<capability>/spec.md` — the CURRENT contract (12
  capabilities: agent-contract, asset-management, context-curation,
  document-ingest, document-lifecycle, document-pipeline, document-render,
  document-revise, document-template, document-visuals,
  template-provisioning, workspace-config). New SDD changes delta against
  these.
- `openspec/changes/<change>/` — active SDD changes, if any (none right
  now). `state.yaml` is the phase record; tasks.md checkboxes are the truth
  of progress; planning artifacts are frozen, additive edits only.
- `openspec/changes/archive/2026-07-06-universal-doc-harness/` — full audit
  trail of the founding refactor (proposal/design/tasks/state +
  archive-report.md with the PR ledger).
- `plans/` (19 md, ~1 MB) and `specs/` (2 design docs at the repo root) are
  **HISTORICAL, not planning sources**: the playbook and design docs of a
  finished migration whose code shape two later SDD changes refactored past.
  See the status note at the end of `plans/roadmap.md`. The spec→code bridge
  excludes `plans/` for this reason.
- `RESUME.md` — session-resume prompt and tool authority hierarchy
  (OpenSpec > Gentle AI/SDD > superpowers > engram/codegraph/context7/rtk).
- `.atl/skill-registry.md` — skill index for sub-agent launches.

## Knowledge graphs — three indexes, one routing rule

Three graphs index this repo. They overlap on disk (that is free) but must
not overlap on questions (that is the token tax). Route, do not poll all
three.

| Need | Tool | Entry point |
|---|---|---|
| Source to read or edit; what a change touches | CodeGraph | `codegraph_explore` |
| Data/control flow, taint, "what breaks if" | GitNexus | `pdg_query`, `impact`, `trace`, `cypher` |
| Which symbols a diff touches | GitNexus | `gitnexus detect-changes` |
| Why something exists; spec ↔ code rationale | graphify | `graphify query`, `explain` |
| Architectural hubs, subsystem map | graphify | `graphify god-nodes` |

Tiebreaker: **needs code bytes → CodeGraph. Follows a value → GitNexus.
Answers a "why" → graphify.**

- CodeGraph — `.codegraph/`, live watcher, ~1s lag. Query from inside the
  repo so the nearest index wins.
- GitNexus — `.gitnexus/` (self-ignoring). Rebuild:
  `gitnexus analyze --index-only --pdg`. `--pdg` is the whole point; without
  it this is a slower CodeGraph. `--index-only` keeps it from rewriting
  `CLAUDE.md`/`AGENTS.md`. Carries ~24k CFG/CDG/REACHING_DEF edges the other
  two do not have.
- graphify — `graphify-out/` (gitignored). Code layer: `graphify update .`
  (AST only, no LLM). Doc/spec layer needs the agent pass: `/graphify --update`.
  `.graphifyignore` scopes what the doc layer reads, mirroring the bridge's
  provenance tiers: `openspec/specs` + `AGENTS.md`/`CLAUDE.md` (contract) and
  `openspec/changes/archive` (rationale) are IN; `plans/`, `specs/` and the
  tooling docs under `.superpowers/`/`.atl/` are OUT. Unscoped, 74% of the
  2.6 MB markdown corpus is a finished migration's playbook and 20% is
  tooling documentation — an extraction pass would spend ~94% of its budget
  on material that says nothing about the harness as it is today.

### Spec-to-code bridge

All three graphs leave markdown as islands (`document <-> code` edges: 0
everywhere). `tools/spec_code_bridge.py` closes that: a symbol written in
backticks inside a spec becomes an EXTRACTED `references` edge, so
`graphify explain <symbol>` returns the ADRs and design decisions behind a
function, not just its callers. No LLM, no inferred edges.

Every edge carries a `provenance` tier: `contract` (`openspec/specs/`,
`AGENTS.md`, `CLAUDE.md`) or `rationale` (`openspec/changes/archive/`,
`specs/`). `plans/` emits nothing — measured before that rule existed, it
supplied 1577 of 2405 edges against 25 from the standing contract, so the
"why" layer was 97% archaeology and answered from a superseded slice plan 63
times out of 64. `tests/architecture/test_spec_symbol_references.py` keeps
the contract side honest by requiring every capability spec to name at least
three real symbols.

    graphify update . && uv run python tools/spec_code_bridge.py

The rebuild drops the bridge, so always chain the two. Re-running the bridge
alone is a no-op. Do NOT use `graphify merge-graphs` for this -- it is a
cross-repo tool and namespaces ids (`repo-2::...`), forking every endpoint
into a ghost duplicate.

### Feedback loop

After a graph-answered question, record whether it helped:

    graphify save-result --question Q --answer A --outcome useful|dead_end|corrected

`graphify reflect` distils those into `graphify-out/reflections/LESSONS.md`.
Feed it results from all three graphs -- it is the only memory layer of the
three, and it is what keeps routing honest over time.

## Mechanised invariants (what fails the build, and where)

| Rule | Test | Needs an index? |
|---|---|---|
| `cli → application → domain`, infra implements ports | `test_graph_invariants.py` | yes (GitNexus) |
| Every `.docx`/zip writer ends in `normalize_docx_zip_timestamps` | `test_docx_writer_invariant.py` | no |
| Every capability spec names ≥3 real symbols, and no dead ones | `test_spec_symbol_references.py` | no |
| Every CLI command has help text | `tests/unit/cli/test_command_help_coverage.py` | no |
| Every emitted `Issue.code` is in the catalog, and vice versa | `tests/unit/domain/test_issue_codes.py` | no |
| `AGENTS.md` never documents a command that does not exist | `tests/unit/test_agents_md_content.py` | no |

The first one needs an index, so CI gives it one: a separate `architecture`
job installs GitNexus, indexes the checkout (~45s) and sets
`ARCHITECTURE_REQUIRE_GRAPH=1`, turning a missing index from a skip into a
failure. It still skips locally. The rest always run, so a fresh clone gets
real enforcement rather than a green vacuum.

### CI jobs, and why there are three

| Job | Guards | Cost |
|---|---|---|
| `check` | ruff, mypy, the suite, a 93% coverage floor | ~1 min |
| `architecture` | the hexagonal layering rule, against a real GitNexus index | ~1.5 min |
| `toolchains` | every optional-toolchain path, with LibreOffice/Java/mmdc/resvg installed | ~4 min |

Three jobs rather than one because they fail at different speeds: lint and
types fail in seconds and must not queue behind a LibreOffice install.

`toolchains` exists because the gate had a SMALLER surface than a developer
desk. Measured: `check` ran 1575 tests and skipped 16; a laptop ran 1584 and
skipped 7. The nine-test gap was mermaid, resvg and Java-backed PDF ingest —
and the seven LibreOffice tests were exercised by nobody, anywhere. That job
also fails if more than 2 tests skip WITH the full toolchain installed: a
toolchain that silently stops installing would otherwise turn the suite green
by skipping, which is the exact failure mode it was added to end.

### Determinism is scoped to a toolchain

`.md` -> `.docx`/HTML is byte-identical for a given pandoc, NOT across pandoc
versions — different releases emit different bytes for identical input. What
holds across versions is document STRUCTURE, which
`tests/integration/test_assembled_structure_golden.py` pins (it passed on
pandoc 3.1.3 in CI and 3.10 locally). `docs doctor` reports the pandoc
version so a post-upgrade change in output is explainable in one command,
and warns below 2.19 (the floor `--embed-resources` sets for `--format
html`). See `AGENTS.md` §7. Each carries its own
probe test against a vacuous pass — an AST walk that stops matching would
otherwise report "0 violations" forever.

`tests/architecture/test_graph_invariants.py` enforces the layering rule
above against the GitNexus graph, and skips when no index is present -- set
`ARCHITECTURE_REQUIRE_GRAPH` to any enabling value (`1`, `true`, `yes`, `on`)
to make a missing index fail instead, so CI can demand the check rather than
accept a silent skip. Nothing sets it yet -- this repo has no CI config.
`tests/architecture/test_spec_code_bridge.py` covers the bridge from its own
fixtures and needs no graph, so it always runs.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%). Format flags (-c, -l, -L, -o, -Z) run raw.
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```
<!-- /rtk-instructions -->
