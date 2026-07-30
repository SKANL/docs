# AGENTS.md — driving the `docs` harness end-to-end

This file is the single, authoritative, agent-agnostic contract for how to
generate a document with this harness over the CLI and the filesystem,
without reading source or tests. It works for any code agent (Claude Code,
Codex, OpenCode, or a human). The exact same content is available at any
time via `docs guide` — both surfaces render from this one file (see
"Single source of truth" below).

## Installation & invocation

Run the CLI from inside this harness project, either form works:

```
uv run python -m docs.cli.main <command>   # from a source checkout
docs <command>                             # installed entry point (pyproject: docs = "docs.cli.main:main")
```

The **document workspace** (where `documents_dir`/`templates_dir` live) is
independent of where the harness code lives — it can be any directory on
disk. Point the CLI at it via `docs.config.json`, the
`DOCS_DOCUMENTS_DIR`/`DOCS_TEMPLATES_DIR` env vars, or by running
`docs doc init` from inside the workspace directory (see §2).

If your working directory is the document workspace and not this harness
checkout (no `pyproject.toml`/`.venv` here), run the CLI via `uv`'s
`--project` flag pointed at the harness checkout instead of a source-checkout
`cd`:

```
uv run --project <path-to-harness> python -m docs.cli.main <command>
```

Do **not** use `uv run --directory <path-to-harness> ...` for this: it
changes `uv`'s project root to the harness checkout and silently writes
`docs.config.json`/other resolved-cwd artifacts *there* instead of your
workspace — `--project` keeps `uv`'s project resolution on the harness while
leaving your invocation's cwd (and therefore config resolution, §2) alone.

## 0. Mental model: mechanical core vs. cognitive slots

The harness is deterministic and format-agnostic: given the same inputs
(section Markdown, context, template, assets) it produces the same output
every time. It does ALL of the mechanical work — parsing, numbering,
rendering, validating structure, running the review heuristics. It never
guesses prose.

- **Harness-mechanical** (never author this by hand): figure/table
  numbering, cross-reference resolution, section ordering, cover/TOC
  assembly, `.docx` structure, deterministic zip output, review findings.
- **Agent-cognitive slot** (the ONLY thing you author): the prose body of
  each section's `.md` file — the actual sentences, arguments, and
  evidence synthesis that make the document say something.

Section `.md` files carry a harness-managed `---{...JSON...}---` front-matter
header (hashes, review/scaffold metadata) above the prose body. **Edit only
the Markdown body below the header**, never the header itself — the header
is rewritten for you by `build-section` (initial scaffold — see the WARNING
in §1/§4), `docs stamp-section <id> --by <who>` (recomputes `body_hash`,
records `authored_by`; the command to run after hand-authoring), and
`doc revise` (§5). `review-section` does **not** touch the header — it only
reads the section and reports issues; running it does not update
`body_hash`/`authored_by`.

Everything below exists to get you to and through that one cognitive slot
as fast as possible, then verify the result mechanically.

## 1. End-to-end workflow

```
docs doc init                       # 1. bootstrap workspace + seed a template
docs template use <builtin-id>      # 2. (only if init didn't already seed one)
docs doc new <id> --template <type> # 3. create a document, mark it active
# 4. drop raw source material (PDFs, docx, md, images) into <doc>/inbox/
docs pipeline ingest                # 5. convert inbox/ sources to markdown + assets
docs doc status --json              # 6. see what's filled, what's missing, what's next
docs context set <topic> <field> <value>   # 7. fill required context fields
docs pipeline prep                  # 8. scaffold section files from the template (runs build-section per section, once)
# 9. author: edit sections/NNN-<id>.md bodies (the cognitive slot)
docs stamp-section <id> --by <agent> # 10. record provenance + recompute body_hash (recommended, see §0/§4)
docs review-section <id> --json     # 11. iterate to green (see loop below)
docs pipeline assemble              # 12. render the final output(s), --format html|pdf|docx
docs verify                         # 13. structural + audit verification
# 14. optional, after a first assemble: docs doc revise <id> "<request>" <file>
docs doc mark-final                 # 15. optional: flip lifecycle draft -> final, snapshot draft build into output/final/
```

**WARNING — `build-section` vs `stamp-section`: not interchangeable.**
`docs build-section <id>` (**re**)generates a section **from the template
scaffold** — it is the initial-scaffolding command (`pipeline prep` runs it
once for every section) and must **not** be run again on a section you have
already hand-authored. The harness protects you — if it detects authored
content it diverts the regenerated scaffold to `sections/_proposals/<id>.candidate.md`
and leaves your prose untouched — but you are then left with a stray candidate
to reconcile, and the command is simply the wrong tool once authoring has begun.
`docs stamp-section <id> --by <agent>` is the safe command to
run after authoring — it never touches the prose body, it only rewrites the
front-matter header (`body_hash`, `authored_by`, `model`). If in doubt after
authoring, run `stamp-section`, never `build-section`.

Every step has a corresponding CLI command; run `docs --help` or
`docs <group> --help` for the full option surface. `docs doctor` is
available at any point to fail-open-diagnose the workspace (missing
optional inputs WARN with a next step; `--strict` restores hard-fail for
CI).

**A git repository is optional.** The workspace does not need to be a git
repo. On a non-git workspace, commands that opportunistically read git
metadata (revision, remote, per-file history) fail closed internally and
print harmless stderr lines such as `git rev-parse --short HEAD failed in
...` / `git remote get-url origin failed in ...` during `pipeline`/`verify`/
`doctor` — this is expected, not an error; the command still exits `0`.

Two `docs doctor` checks worth knowing up front:
- **`manual_dir`** (an optional writing-guide directory, usually under
  `inbox/`): if absent, doctor WARNs that no manual/guide was detected and
  the document will use default rules — non-blocking.
- **`build-rules`** is a real subcommand (`docs build-rules`), but it
  already runs automatically as a stage of `docs pipeline prep`. Doctor's
  WARN about a missing rules manifest is usually already resolved by the
  time an agent runs `pipeline prep`; running it manually is only needed
  outside the normal `prep` flow.

### Command groups

| Group | Purpose |
|---|---|
| `doc` | document CRUD: `init`, `new`, `list`, `current`, `show`, `use`, `rename`, `delete`, `status`, `revise`, `mark-final` |
| `template` | template CRUD: `list [--available]`, `use <builtin-id>`, `show`, `init`, `validate` |
| `context` | atomic context fields: `status`, `elicit`, `ingest`, `show`, `set`, `rm` |
| (flat, no prefix) | `doctor`, `pipeline <stage_set>`, `verify`, `history`, `stamp`, `guide`, `build-section`, `stamp-section`, `pack-context`, `review-section`, `review-document`, `collect-sources`, `build-rules`, `review-rules`, `collect-issues`, `collect-code-evidence`, `build-ledger` |
| `asset` | asset registration commands |
| `docx` | low-level `.docx` inspection commands |

### Pipeline stage sets

`docs pipeline <stage_set>` accepts `prep | ingest | assemble | all`.
**`ingest` must run before `assemble`/`all` whenever sources exist in
`inbox/`** — `all` does NOT include the ingest stages by design (ingest is
a separate, re-runnable conversion step, not always needed).

### Output-format selection: `--format`

`docs pipeline assemble --format <fmt>` selects which artifact(s) to build;
the flag is repeatable (`--format html --format pdf --format docx`) and
defaults to the document's configured `output.format` (`docx`) when
omitted — existing single-format workflows are unaffected.

- `docx` and `html` are **byte-deterministic**: rebuilding unchanged
  sections twice produces byte-identical output (see §5).
- `pdf` is a **derived, non-byte-deterministic** artifact, rendered from
  the built `.docx` via LibreOffice/`soffice`. It is explicitly NOT held to
  the byte-identity guarantee (rendering engine/version affects output
  bytes even for identical inputs). When `soffice` is not on `PATH`, the
  build WARNs to stderr and **skips** the PDF artifact — every other
  requested format still builds successfully; this is not a failure.

**Output filenames derive from the document id by default.** Assembled
files default to `<doc-id>-draft.docx`, `<doc-id>-body.docx`, and
`<doc-id>-draft.html` (e.g. `faro-draft.docx` for a document with id
`faro`) — a template may still declare explicit names via
`output.draft_name`/`body_name`/`html_name` in its config, which win over
the id-derived default; `reporte-estadia-tic` does this (its `output` block
declares `tesina-draft.docx`/`tesina-body.docx`/`tesina-draft.html`
explicitly), so only estadia documents ship as `tesina-*` files —
`technical-report-srs` and `documento-generico` documents ship as
`<doc-id>-*` by default. The rendered HTML `<title>` is the document's
title: the template's declared `title` if the document config has one,
else the document id — never the first section's filename stem (pandoc's
own fallback when no `--metadata title=` is passed, which the harness
always passes).

### Ingest & classification: advisory, and never auto-injected into sections

`docs pipeline ingest` converts every file in `inbox/` to Markdown at
`sections/ingested/<stem>-<kind>-<sha8>.md` and reports what it found in
`inbox/intake-report.md` (a human-readable Found / Missing / How-to-finish
summary) and `inbox/_classification-queue.json` (one entry per source file:
`proposed_role`, `confidence`, `signals`, `confirmed_role`).

**Classification is advisory, not a gate.** In the default (non-`--strict`)
mode, `pipeline ingest` still succeeds (exit 0) even when a file's role is
`unknown` or low-confidence — arbitrarily-named source files are common and
expected. There is no CLI command that "confirms" a role: hand-edit
`_classification-queue.json`, setting `confirmed_role` on an entry, and the
*next* `pipeline ingest` run reads it back. `confirmed_role` accepts exactly
one of `evidence | example | normative` — any other value (a typo, a
section id, `unknown`) is rejected with a WARNING and the entry stays
pending, same as if it were never confirmed. Confirming a role only clears
that file's count in `doc status --json`'s `classification_pending` field
(§6) — **it does not write anything into a section.**

**The harness never writes section prose, ever.** Converted source material
under `sections/ingested/*.md` (plus `inbox/intake-report.md` and, once
built, `sections/00-fact-ledger.md`) is authoring *reference* material
only. To fill a section's cognitive slot (§0), the agent MUST read that
material and WRITE the section's `.md` body itself — no pipeline stage,
ingest step, or classification action ever copies ingested content into
`sections/NNN-<id>.md`. Treating "ingest ran" or "a role got confirmed" as
"section content done" is the most common way to end up with an empty or
scaffold-only section that later fails `review-section`.

## 2. Config resolution

Workspace roots (`documents_dir`, `templates_dir`) resolve with this
precedence, highest first:

1. `docs.config.json` in the current working directory (written by
   `docs doc init`, or hand-edited: `{"documents_dir": "...", "templates_dir": "..."}`)
2. environment variables `DOCS_DOCUMENTS_DIR` / `DOCS_TEMPLATES_DIR`
3. defaults: `documents/`, `templates/` (relative to cwd)

A malformed `docs.config.json` WARNs to stderr and is ignored — config
resolution never bricks a command (fail-open).

`docs doc init` bootstraps a fresh workspace: writes `docs.config.json`,
creates `documents_dir`/`templates_dir`, and — if `templates_dir` is
empty — seeds it with the built-in templates (`docs template list
--available` lists what is shippable; `docs template use <id>` copies one
in explicitly). Both `init` and `use` refuse to clobber an existing,
differing file unless `--force` is passed.

Three built-in templates ship today: `reporte-estadia-tic` (Spanish, APA7
citations), `technical-report-srs` (English, no citation style), and
`documento-generico` (a minimal generic-document template). Review rules
(contested/forbidden terms, citation style, structural sections) are
declared **per template**, not hardcoded — a new template can define its
own review behavior without any code change; `technical-report-srs` and
`documento-generico` are concrete examples of structurally different,
non-APA templates working end-to-end.

### Context fields: the `context set <topic> <field> <value>` key convention

Field keys are **exact matches** against the topic's declared field keys in
its template — not fuzzy, case-insensitive, or aliased. There is no
dedicated schema-introspection command: `docs context status` lists topics
and what's missing but not field keys; use `docs template show <id>` and
read `context_schema.topics[].fields[].key` to see a topic's real keys (if
that's unavailable, keys are lowercase identifiers matching the field's
label). Two shapes:

- **Structured topic** (multiple named fields), e.g. `alumno` in
  `reporte-estadia-tic`: `docs context set alumno nombre "Ada Lovelace"`,
  `docs context set alumno carrera "Ing. en Sistemas"` (also has
  `grado_grupo`, `asesor`, `segundo_revisor`).
- **Prose topic** (one free-text value, no `fields` list), e.g. `proyecto`:
  `docs context set proyecto _ "<full prose>"` — the CLI still requires a
  `<field>` positional, but it is ignored for prose topics, so any
  placeholder value (`_`, `texto`, ...) works.

## 3. Figure/table convention: symbolic labels, numbers computed at build

Authors never write literal figure/table numbers by hand. Write symbolic
markers in the section body; the build assigns numbers deterministically,
in document order, then in first-appearance-in-text order:

```
[[figure:my-diagram]]      -> becomes "Figura N." (a caption prefix)
[[table:cost-breakdown]]   -> becomes "Tabla M."
[[ref:my-diagram]]         -> becomes "Ver Figura N" wherever referenced
```

Rules:
- The same label always resolves to the same number within one build; the
  numbers themselves are recomputed fresh every build (never store a
  number in the `.md` — that would violate the reproducibility boundary,
  §5).
- An unresolvable `[[ref:label]]` renders as `Ver Figura ?` plus a build
  WARNING naming the label — never a silent guess.
- Reordering sections renumbers automatically and deterministically; no
  manual renumbering pass is ever required.

## 4. The review loop: `review-section --json` iterate-to-green

**Never run `build-section` on a section you are about to review or have
already authored** — it regenerates from the template scaffold (authored
content is protected, but diverted to a `_proposals/` candidate you must then
reconcile — see the WARNING in §1). Use `stamp-section` instead
once authoring settles (below); `review-section` itself is always safe —
it only reads and reports, it never writes.

`docs review-section <id> --json` is the machine-checkable target for a
section's authored prose. Loop:

1. Run `docs review-section <id> --json`.
2. If `"passed": false`, read `"issues"` — each issue names the failing
   check and a human-readable detail (missing required content, an
   unsubstantiated subjective/contested term, an inconsistency against the
   template's normative rules, etc.).
3. Edit the section's `.md` body to address the issue (add the missing
   content, add quantified evidence or a citation next to a flagged claim,
   resolve the inconsistency).
4. Re-run step 1. Repeat until `"passed": true`.
5. Run `docs stamp-section <id> --by <agent>` to record provenance and
   recompute `body_hash` for the now-reviewed body (recommended — see §0).
6. `docs review-document --json` runs the same check across every section
   at once, for a final pre-assemble sweep.

Review checks are evidence-aware: a subjective or contested term next to
a citation, a quantified figure, or an explicit qualifying statement in
the same clause is NOT flagged — only a bare, unsubstantiated claim is.
`--strict` tightens optional checks to hard failures (useful in CI).

**Scaffold hint text can be generic — the template's declared rules win,
not the hint.** `pipeline prep`'s scaffolded section bodies include
boilerplate reminders (e.g. a references-section hint mentioning "APA 7")
that are not always conditioned on the active template's `citation_style`;
a `citation_style: none` template (e.g. `technical-report-srs`) can still
scaffold that APA-flavored hint line. If a scaffold hint ever conflicts
with what the template actually declares (`context_schema`,
`section_contracts`), follow the template — `review-section` enforces the
template's real rules, never the hint text.

## 5. Semantic revision loop: `docs doc revise`

Use `docs doc revise` for a targeted, post-completion edit to already-authored
content — not the first-pass authoring in §4, which is direct `.md` editing.
It is the tool for "the reviewer/agent asked for this one change" after a
section (or a context topic) is already written and reviewed:

```
docs doc revise <target-id> "<request>" <body-file> [--field <key>] [--json]
```

- `<target-id>` is either a **section id** (edits that section's prose) or a
  **context topic id** (edits a context field/value — the "ripple" case
  below). Anything else (an unknown id, or a request to add/remove a
  section) is rejected: `revise` never performs structural changes — use
  `docs pipeline prep`/`docs context set`/ingest for that.
- `<body-file>` is a `.md` file the agent has already written out-of-band
  with the full replacement body/value — `revise` never generates prose
  itself, it only applies, diffs, and re-validates it.
- `--field <key>` is required only when the target is a non-prose context
  topic with multiple fields.

What the harness does mechanically, every call:
1. Writes the new body/value, replacing the old.
2. Computes a unified diff (before → after) and snapshots it under
   `sections/_revisions/<target>.<n>.diff`.
3. Re-validates **only what changed**: the edited section (`review-section`)
   or, for a context-topic edit, every section that topic's template
   declares as a consumer (the "ripple") — plus one `review-document` sweep.
   Unrelated sections are never re-reviewed.
4. Appends one entry (`request`, `section_id`/topic id, `diff_path`,
   `before_hash`, `after_hash`, `ripple: [...]`, timestamp) to
   `sections/_revisions/revision-log.json` — an append-only provenance log,
   never rewritten in place.

`docs apply-corrections` is a different, narrower tool: mechanical
find/replace over already-authored text (typo/wording fixes), with no diff
snapshot or ripple. Use `revise` for a semantic rewrite of a section's
argument/content; use `apply-corrections` for literal text substitutions.

## 6. Document lifecycle and build version

Every document starts `lifecycle: draft`. `docs doc mark-final [<id>]`
(defaults to the active document) flips it to `final` — a one-way,
user-driven signal with no effect on build mechanics; it exists so an agent
or reviewer can tell, from `docs doc status --json`, whether a document is
still being iterated on or considered done.

**`mark-final` also promotes the current draft build into `output/final/`.**
Beyond flipping the lifecycle flag, `docs doc mark-final` copies every file
currently in `output/draft/` into `output/final/` — a **point-in-time
snapshot**, not a live mirror: it reflects whatever was last built at the
moment `mark-final` ran. If you edit a section and re-assemble afterward,
`output/draft/` moves ahead and `output/final/` is now stale — **re-run
`docs doc mark-final` to re-sync it** after any further edit+assemble cycle.
If `output/draft/` is empty when `mark-final` runs (nothing has been
assembled yet), it WARNs and promotes nothing — `mark-final` never fails,
but `output/final/` stays empty until at least one `pipeline assemble` has
run. `docs doc status --json`'s `output.final_exists` reflects whether
`output/final/` currently has any file in it (see the table below).

Each `docs pipeline assemble`/`all` run appends a `build_version` (an
incrementing integer, starting at `1`) to the document's `runs/` history —
this is a wall-clock log, not part of the deterministic build artifact
(§7). `docs doc status --json` surfaces both fields directly:

```json
{ "doc_id": "...", "lifecycle": "draft", "build_version": 2, ... }
```

`build_version` is `null`/absent before the first assemble run.

### `doc status --json` field reference

| Field | Meaning |
|---|---|
| `sections.missing` | Section id has no file on disk yet. |
| `sections.scaffold` | Section file **exists** but is still boilerplate: its metadata says `authored_by: harness-scaffold`, or its body still contains a literal `PENDIENTE` marker. This is NOT a general "still needs work" flag — a hand-authored section with no leftover `PENDIENTE` text is never listed here, even if `review-section` still finds issues on it. |
| `sections.needs_review` | Section exists and `review-section` currently reports one or more issues — tracked independently of `scaffold`. |
| `sections.authored` | Raw count of section files that exist on disk, regardless of scaffold/needs_review state. |
| `ingest.classification_pending` | Count of `inbox/_classification-queue.json` entries with no `confirmed_role` yet (§1). |
| `figures.count` | Number of entries in `sections/figure-catalog.json`, built by `pipeline ingest` from image assets found under `inbox/` (declared + heuristically-detected images, plus rendered vector-PDF pages). It is **not** a count of inline `[[figure:label]]` markers (§3) — those are independent, resolved/numbered only at build time, and never increment this field; a section can reference figures via `[[figure:...]]` with `figures.count` still `0` if no image ever went through `pipeline ingest`. |
| `lifecycle` | `"draft"` or `"final"`, set by `doc mark-final` (above). |
| `build_version` | Highest `build_version` recorded under `runs/`, or `null` before the first `pipeline assemble`. |
| `output.final_exists` | Whether `output/final/` currently contains any file — becomes `true` after a `doc mark-final` run that had a non-empty `output/draft/` to promote (above); stays `false` before the first successful promotion. |

## 7. Reproducibility boundary (read this before worrying about "identical output")

**Section `.md` files are the durable source of truth.** The built
`.docx`/HTML output is a **deterministic pure function** of those `.md`
files plus the template and configuration — same inputs, byte-identical
output, every time, on every machine. No timestamps, no wall-clock, no
non-deterministic iteration order anywhere in the build path.

**Byte-determinism binds `.md` → `.docx`/HTML only.** `pdf` (see §1
Output-format selection) is an explicitly excepted, derived artifact:
non-byte-deterministic and never held to this guarantee.

This means:
- Rebuilding **without editing any section** twice in a row MUST produce a
  byte-identical `.docx`/HTML. If it doesn't, that is a harness bug, not
  environmental noise.
- **Editing a section's prose between two builds is not a determinism
  violation.** The output legitimately changes because the source changed
  — that is authoring, not nondeterminism. Only an *unchanged* source
  producing a *different* `.docx`/HTML output is a bug.
- Figure/table numbering (§3), provisioned templates, and config files are
  all held to the same standard: deterministic functions of their inputs.
- A PDF differing byte-for-byte between two builds of the same unchanged
  sources is expected (rendering-engine/version dependent) and is NOT a
  bug — see §1.

## 8. Where things live (for orienting, not for hand-editing)

```
<documents_dir>/<doc-id>/
  document.json           # active template/config; lifecycle (draft|final)
  inbox/                  # drop raw source material here; docs pipeline ingest converts it
  sections/                # your cognitive-slot .md files (NNN-<id>.md) + generated manifests
    ingested/               # docs pipeline ingest output: <stem>-<kind>-<sha8>.md -- authoring-reference source material, read but don't hand-edit
    _revisions/             # docs doc revise: per-edit .diff snapshots + revision-log.json
  context/                # per-topic context fields (docs context set/status)
  assets/                 # figures/images referenced by sections
  output/draft|final/     # rendered .docx/html/pdf output; draft/ is always the current build, final/ is a snapshot copy `doc mark-final` promotes it into (see §6)
  runs/                   # command history + build_version (docs history, docs doc status)
```

## Single source of truth

This file IS the canonical content — `docs guide` prints these exact
bytes (read from the installed package's copy, or this file directly in a
source checkout). There is exactly one place this guidance is written;
editing this file is the only edit needed, and a packaging test in the
harness's own suite asserts the installed copy never drifts from it.
