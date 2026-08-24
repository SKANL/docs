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
- Lint/typecheck: `ruff check .` / `mypy src` (ambient tools, not yet declared)

## Layout

- `src/docs/domain/` — pure logic + `ports/` (typing.Protocol interfaces)
- `src/docs/application/` — services, depend on ports only
- `src/docs/infrastructure/` — adapters (filesystem, python-docx, pandoc)
- `src/docs/cli/` — Typer CLI; composition root in `cli/_shared.py` (Deps)
- `tests/unit/`, `tests/integration/` — mirror the src layers

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

- Any new `.docx`/zip writer MUST end in
  `infrastructure/docx/deterministic_zip.py:normalize_docx_zip_timestamps` —
  stdlib zip stamps wall-clock entry times at 2s DOS granularity, so a
  "flaky" byte-identity test is a product bug, not test noise.
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

### Spec-to-code bridge

All three graphs leave markdown as islands (`document <-> code` edges: 0
everywhere). `tools/spec_code_bridge.py` closes that: a symbol written in
backticks inside a spec becomes an EXTRACTED `references` edge, so
`graphify explain <symbol>` returns the ADRs and design decisions behind a
function, not just its callers. No LLM, no inferred edges.

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
