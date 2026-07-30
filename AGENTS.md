# AGENTS.md — driving the `docs` harness end-to-end

This file is the single, authoritative, agent-agnostic contract for how to
generate a document with this harness over the CLI and the filesystem,
without reading source or tests. It works for any code agent (Claude Code,
Codex, OpenCode, or a human). The exact same content is available at any
time via `docs guide` — both surfaces render from this one file (see
"Single source of truth" below).

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
docs pipeline prep                  # 8. scaffold section files from the template
# 9. author: edit sections/NNN-<id>.md bodies (the cognitive slot)
docs review-section <id> --json     # 10. iterate to green (see loop below)
docs pipeline assemble              # 11. render the final output(s), --format html|pdf|docx
docs verify                         # 12. structural + audit verification
# 13. optional, after a first assemble: docs doc revise <id> "<request>" <file>
docs doc mark-final                 # 14. optional: flip lifecycle draft -> final
```

Every step has a corresponding CLI command; run `docs --help` or
`docs <group> --help` for the full option surface. `docs doctor` is
available at any point to fail-open-diagnose the workspace (missing
optional inputs WARN with a next step; `--strict` restores hard-fail for
CI).

### Command groups

| Group | Purpose |
|---|---|
| `doc` | document CRUD: `init`, `new`, `list`, `current`, `show`, `use`, `rename`, `delete`, `status`, `revise`, `mark-final` |
| `template` | template CRUD: `list [--available]`, `use <builtin-id>`, `show`, `init`, `validate` |
| `context` | atomic context fields: `status`, `elicit`, `ingest`, `show`, `set`, `rm` |
| (flat, no prefix) | `doctor`, `pipeline <stage_set>`, `verify`, `history`, `stamp`, `guide`, `build-section`, `pack-context`, `review-section`, `review-document`, `collect-sources`, `build-rules`, `review-rules`, `collect-issues`, `collect-code-evidence`, `build-ledger` |
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

Two built-in templates ship today: `reporte-estadia-tic` (Spanish, APA7
citations) and `technical-report-srs` (English, no citation style). Review
rules (contested/forbidden terms, citation style, structural sections) are
declared **per template**, not hardcoded — a new template can define its
own review behavior without any code change; `technical-report-srs` is a
concrete example of a structurally different, non-APA template working
end-to-end.

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
5. `docs review-document --json` runs the same check across every section
   at once, for a final pre-assemble sweep.

Review checks are evidence-aware: a subjective or contested term next to
a citation, a quantified figure, or an explicit qualifying statement in
the same clause is NOT flagged — only a bare, unsubstantiated claim is.
`--strict` tightens optional checks to hard failures (useful in CI).

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

Each `docs pipeline assemble`/`all` run appends a `build_version` (an
incrementing integer, starting at `1`) to the document's `runs/` history —
this is a wall-clock log, not part of the deterministic build artifact
(§7). `docs doc status --json` surfaces both fields directly:

```json
{ "doc_id": "...", "lifecycle": "draft", "build_version": 2, ... }
```

`build_version` is `null`/absent before the first assemble run.

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
    _revisions/             # docs doc revise: per-edit .diff snapshots + revision-log.json
  context/                # per-topic context fields (docs context set/status)
  assets/                 # figures/images referenced by sections
  output/draft|final/     # rendered .docx/html/pdf output
  runs/                   # command history + build_version (docs history, docs doc status)
```

## Single source of truth

This file IS the canonical content — `docs guide` prints these exact
bytes (read from the installed package's copy, or this file directly in a
source checkout). There is exactly one place this guidance is written;
editing this file is the only edit needed, and a packaging test in the
harness's own suite asserts the installed copy never drifts from it.
