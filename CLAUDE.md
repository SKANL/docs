# docs — document-creation harness

Format-agnostic, deterministic document-creation harness (hexagonal
architecture). The harness does all mechanical work; the AI model only fills
structured cognitive slots. Currently mid-refactor under the SDD change
`universal-doc-harness`.

## Commands

- Test: `uv run pytest` (strict TDD — write the failing test first, always)
- Run CLI: `uv run python -m docs.cli.main --help`
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
- Determinism: same inputs must produce identical outputs; no timestamps or
  randomness in generated artifacts.

## Active work — read on demand (do not @import)

- `openspec/changes/universal-doc-harness/state.yaml` — current SDD phase and
  session config. Start here when resuming work.
- `openspec/changes/universal-doc-harness/tasks.md` — task checklist; the
  checkboxes are the source of truth for implementation progress.
- `openspec/changes/universal-doc-harness/{proposal.md,design.md,specs/}` —
  planning artifacts (frozen; additive updates only).
- `RESUME.md` — session-resume prompt and tool authority hierarchy
  (OpenSpec > Gentle AI/SDD > superpowers > engram/codegraph/context7/rtk).
- `.atl/skill-registry.md` — skill index for sub-agent launches.

## CodeGraph

This repo has its own index at `docs/.codegraph` — always query from inside
the repo so the nearest index wins. Use `codegraph_explore` before editing.

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
