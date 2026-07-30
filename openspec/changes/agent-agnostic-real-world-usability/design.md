# Design: Agent-Agnostic Real-World Usability

> Technical design (the architectural HOW). Steps/tasks are owned by
> `sdd-tasks`. Every decision below is grounded in current on-disk code with
> `file:line` citations. Bound decisions 1–3 from the proposal are inputs, not
> re-litigated here.

## 1. Architecture approach

The harness is hexagonal (`domain/` pure logic + `ports/`, `application/`
services on ports, `infrastructure/` adapters, `cli/` Typer + composition root
in `cli/_shared.py`). This change adds **zero new architectural layers**. Every
item lands on one of four existing seams:

| Seam | Where | Items landing here |
|------|-------|--------------------|
| Composition root | `Deps.__init__` (`cli/_shared.py:77`) + `build_workspace` (`:64`) | A (config), F (PDF wiring) |
| Pure domain function extension | `domain/source_role.py`, `domain/rules.py`, new `domain/*` modules | D, H, J, K, M |
| Application service method | `DoctorService` (`application/doctor.py:18`), `ContextService.build_gap_report` (`application/context.py:130`), `IngestService` (`application/ingest.py`) | E, G, K, L |
| CLI command | `doc_app`, `template_app`, new `core_app` command | B, C, I |

Two governing principles, both already visible in the codebase and preserved:

- **I/O in adapters, judgment in pure functions.** `classify()`
  (`source_role.py:51`) is explicitly "zero I/O, zero randomness". Item D keeps
  that: a new *adapter* reads file bytes and produces content-signal STRINGS;
  the pure classifier consumes strings only. Same split as the existing
  `image_metadata` port injected into `IngestService` (`ingest.py:145`).
- **Fail-open, never-silent.** The `ingest.py` walk already reports every
  ignored/empty/error path instead of dropping it (`_walk_inbox:204`,
  `_ingest_one_safely:309`). Items D/E/K extend the same contract: low-confidence
  and conflicting inputs are *queued/WARNed with next-steps*, never silently
  defaulted.

### Reproducibility boundary (item M) — the design principle that governs all others

The section `.md` files (agent-authored prose) are the **durable source of
truth**; the `.docx` is a **deterministic pure function of them + the figure
catalog + the template**. Byte-determinism is asserted on the BUILD, not the
prose. Concretely this constrains every other item:

- Anything that writes bytes (config file, provisioned templates, rendered PDF
  pages, numbered captions) MUST be a deterministic function of its inputs — no
  timestamps, no wall-clock, no dict-iteration-order dependence. Any new
  `.docx`/zip writer still terminates in
  `infrastructure/docx/deterministic_zip.py:normalize_docx_zip_timestamps`
  (per repo CLAUDE.md).
- The numbering pass (H) is a pure rewrite over ordered section text → the same
  sections always yield the same numbers.
- Item M ships as a spec statement in `openspec/specs/document-pipeline/spec.md`
  and one paragraph in `AGENTS.md` (item B) — no code.

---

## 2. Per-item design (A–M)

### A. Workspace config + `doc init`

**Current:** `build_workspace()` (`cli/_shared.py:64`) reads only
`DOCS_DOCUMENTS_DIR`/`DOCS_TEMPLATES_DIR` env vars with cwd-relative defaults
(`"documents"`, `"templates"`). No file, no bootstrap. `Workspace`
(`domain/workspace.py:8`) is a frozen 2-field dataclass.

**Design.** Insert a **config-file layer above env**, precedence
`config file → env → default`:

- New pure resolver `domain/workspace_config.py:resolve_workspace_roots(config: dict | None, env: Mapping[str, str], cwd_defaults) -> tuple[Path, Path]`.
  Pure, no I/O — takes an already-parsed dict + an env mapping. Precedence is a
  three-way `or` per field. This keeps `build_workspace` thin and unit-testable
  without touching the filesystem.
- File: **`docs.config.json`** in the **current working directory** (the
  workspace root the agent runs from). JSON — matches every other harness
  artifact (`registry.json`, templates, `document.json`). Schema (both keys
  optional):
  ```json
  { "documents_dir": "documents", "templates_dir": "templates" }
  ```
- `build_workspace()` becomes: read `Path.cwd()/"docs.config.json"` if present
  (best-effort `json.loads`; a malformed file WARNs to stderr and is ignored —
  fail-open), then delegate to `resolve_workspace_roots`. No new dependency;
  `json` + `os.environ` only.
- **`doc init`** — new command on `doc_app` (`cli/commands/doc_app.py:15`):
  1. writes `docs.config.json` (idempotent; refuses to clobber a differing
     existing file without `--force`),
  2. creates `documents_dir` + `templates_dir`,
  3. if `templates_dir` is empty, provisions the built-in template (reuses item
     C's `template use`) so a fresh clone is immediately usable.

**ADR-A.** *Config file in cwd, not `$HOME` or repo.* The workspace is
per-project (documents live in `documents/`). A cwd file travels with the
project and is agent-discoverable via plain `ls`. Rejected: `$HOME/.docs` (not
project-scoped, invisible to a fresh agent), a `[tool.docs]` block in
`pyproject.toml` (couples the harness config to a Python-packaging file the doc
workspace may not have).

---

### B. Agent contract — `AGENTS.md` + `docs guide`

**Current:** no shipped agent guide; `RESUME.md` is SDD-dev-only (per repo
CLAUDE.md). No `docs guide` command.

**Design — single source, two surfaces.** Canonical file lives **once** at repo
root `AGENTS.md` and is **force-included as package data** so the installed
wheel carries it:

```toml
# pyproject.toml
[tool.hatch.build.targets.wheel.force-include]
"AGENTS.md" = "docs/data/AGENTS.md"
```

- **`docs guide`** — new command mounted on `core_app`
  (`cli/commands/core_app.py:17`). Reads the shipped copy via
  `importlib.resources.files("docs.data").joinpath("AGENTS.md").read_text()` and
  prints it. Works from an installed wheel with no repo checkout.
- A single characterization test asserts the repo-root `AGENTS.md` equals the
  packaged bytes (guards drift without a build step).

Content of `AGENTS.md` covers the full agent-agnostic workflow:
`doc init` → drop files in `inbox/` → `pipeline ingest` → read intake/gap report
(G) → `context`/author sections → `review-section --json` iterate-to-green loop
→ `pipeline assemble` → `verify`; the config/env precedence (A); the
figure/table label + `Ver {ref}` convention (H); the cognitive-slot boundary
(harness is mechanical, the agent only fills prose); and the reproducibility
boundary (M).

**ADR-B.** *One canonical file, force-included; not a generated string in
Python.* Keeps the contract editable as plain Markdown and reviewable in PRs.
Rejected: embedding the guide as a Python string constant (unreadable diffs),
or shipping only `AGENTS.md` with no CLI surface (an agent on an installed wheel
can't `cat` a repo file it doesn't have — `docs guide` makes it queryable).

---

### C. Built-in template provisioning

**Current:** the only real template lived under `tests/fixtures/templates/`
(proposal C). `template_app` (`cli/commands/template_app.py:18`) has
`list`/`show`/`init`/`validate`, all operating on `workspace.templates_dir`;
`template init` (`:40`) emits a *skeleton* from `build_template_skeleton`, not a
usable filled template.

**Design.** Ship built-in templates as **package data**, independent of
`tests/fixtures`:

- Layout: `src/docs/templates/builtin/<name>.json` (a real package sub-package
  with `__init__.py` is unnecessary — `importlib.resources.files("docs.templates.builtin")`
  works on a data dir declared to hatch). Seed it by copying the fixture
  template's content into `src/docs/templates/builtin/reporte-estadia-tic.json`
  as the canonical home; the fixture may then re-reference the package copy so
  there is one source.
- Hatch inclusion: `packages = ["src/docs"]` already ships everything under
  `src/docs`; add a `[tool.hatch.build.targets.wheel.force-include]` or
  `artifacts` entry only if `.json` under the package is excluded by default
  (verify with a build; `.json` inside a package dir is normally shipped).
- New commands on `template_app`:
  - `template list --available` — lists names under
    `docs.templates.builtin` (distinct from the existing `template list` which
    lists the workspace `templates_dir`).
  - `template use <builtin>` — copies
    `docs.templates.builtin/<name>.json` → `workspace.templates_dir/<name>.json`
    (refuse-clobber unless `--force`). This is what `doc init` (A) calls to seed
    an empty workspace.

**ADR-C.** *importlib.resources over a hardcoded filesystem path.* The
templates must resolve from an installed wheel where `tests/` does not exist.
`template init` (skeleton authoring) stays as-is and is orthogonal — provisioning
copies a *complete, validated* built-in; `init` scaffolds a *new* type.

---

### D. Content-based classification

**Current:** `classify(relative_path) -> (role, confidence, signals)`
(`domain/source_role.py:51`) is pure, keys off a folder/filename lexicon only.
The module comment at `:40` explicitly defers content probes as "a documented
future extension" — this item is that extension. A flat arbitrary dump yields
all `unknown`/`low` (`:90-91`).

**Design — extend the pure function with an injected content signal, I/O in an
adapter.**

- New port `domain/ports/content_probe_port.py:ContentProbePort.probe(path) -> ContentSignals`
  where `ContentSignals` is a frozen dataclass of *strings/flags only*:
  `pdf_title: str`, `first_headings: tuple[str, ...]`, `head_keywords: tuple[str, ...]`
  (case-folded tokens from the first N bytes), `extension: str`.
- Adapter `infrastructure/ingest/content_probe_adapter.py` implements it:
  extension via existing detector, PDF title/first headings via the already-present
  `pypdfium2`/opendataloader stack (best-effort; any failure → empty signals,
  fail-open), first-N-bytes keyword scan for text/markdown.
- Extend the pure classifier signature to
  `classify(relative_path, signals: ContentSignals | None = None)`. Default
  `None` preserves every existing caller/test byte-for-byte (folder lexicon path
  unchanged). When `signals` is present it contributes *additional weighted
  hits* into the same `scores` machinery (`source_role.py:74-101`): content
  keyword match against `_ROLE_LEXICONS` adds a lower weight than a folder hit,
  higher than a filename-stem hit. Confidence stays the existing `high`/`medium`/`low`.
- **Bound decision (queue vs. act).** Reuse the existing classification-queue
  contract already in `ingest.py` (`_write_classification_queue:192`,
  `inbox/_classification-queue.json`, external-confirmation merge). Rule:
  `confidence == "high"` → act (role assigned in the manifest); `medium`/`low`
  → HELD to the queue for confirmation, never silently defaulted (mirrors the
  existing `unknown`/`low` → queue behavior). The `IngestService` passes the
  probe adapter's output into `classify`; the adapter is injected via `Deps`
  like `image_metadata` already is (`_shared.py:114`).

**ADR-D.** *Signals-as-strings boundary.* The classifier must remain a pure,
deterministic function so its output is reproducible and unit-testable without
fixtures on disk. Passing extracted strings (not a file handle or a Path to
read) keeps the I/O entirely in the adapter — identical to the existing
`image_metadata` split. Rejected: reading bytes inside `classify` (breaks the
module's own stated purity contract at `:52`).

---

### E. Flexible manual_dir + doctor-as-guide

**Current:** `run_doctor` (`application/doctor.py:29`) adds `context_dir` and
`manual_dir` as **required** checks (loop at `:32-36`, `Check` defaults
`required=True`, `domain/doctor.py:12`). `DoctorResult.passed`
(`domain/doctor.py:23`) fails if any required check is `ok=False`. So a missing
manual hard-fails the whole run (proposal E).

**Design — three changes, all fail-open:**

1. **Downgrade optional-input checks to WARN.** `manual_dir` (and any other
   optional input) becomes `required=False` with a *next-step* detail string
   (e.g. "No se detectó un manual/guía en inbox/; el documento se generará con
   las reglas por defecto — agrega la guía a inbox/ para aplicar sus normas.").
   `context_dir` stays required (it is a per-document harness dir always created
   by `DocumentService.create`, `_SUBDIRS`, `application/documents.py:23`, so its
   absence is a genuine breakage, not a missing optional input). `passed`
   (`domain/doctor.py:23`) needs **no change** — it already counts only
   `required` checks; flipping the flag is sufficient.
2. **`--strict` restores hard-fail.** `run_doctor` already threads `strict`
   (`:29`); optional checks that matter in strict mode set
   `required=strict` (the pattern already used for `gh`/`documents_script` at
   `:118,:122`).
3. **Auto-detect the manual by content.** New application helper (in
   `DoctorService` or a small `domain` predicate fed by a probe) scans
   `inbox/` for a manual-like source using the same `ContentProbePort` (D) —
   e.g. a PDF/doc whose title/headings match normative-guide keywords — and, if
   found, reports it as the resolved `manual_dir`/`manual_pdf` in the WARN
   detail. No hardcoded `{inbox}/guides/manual-estadia-tic` path.

`to_markdown` (`domain/doctor.py:26`) already renders `WARN` vs `FAIL`
distinctly — the guide UX is free once the flags flip.

**ADR-E.** *Flip `required`, don't rewrite `passed`.* The domain already models
required-vs-optional correctly; the bug is purely that optional inputs were
marked required. Smallest correct diff. Rejected: adding a severity enum to
`Check` (over-engineering — `required: bool` + strict already expresses it).

---

### F. Wire `Pdfium2PdfRenderAdapter` into ingest

**Current:** `Pdfium2PdfRenderAdapter` (`infrastructure/pdf/pdfium2_pdf_render_adapter.py:46`)
implements `PdfRenderPort` (`domain/ports/pdf_render_port.py:7`) and is fully
tested but **unwired** — `Deps` never constructs it, `IngestService` never calls
it. `_build_figure_catalog` (`application/ingest.py:735`) only turns declared/
heuristic **image** assets into `FigureEntry`s; a vector-only PDF (opendataloader
extracts zero raster) contributes no figures.

**Design.**

- Inject an optional `pdf_render: PdfRenderPort | None` into `IngestService.__init__`
  (`ingest.py:135`), exactly like `image_metadata`. `Deps` constructs
  `Pdfium2PdfRenderAdapter()` and passes it (`_shared.py:110-115`). Import guarded:
  if `pypdfium2`/`PIL` import fails, pass `None` — degrade cleanly (proposal F,
  bound decision 2).
- New step in `_build_figure_catalog` (or a sibling called alongside it): for
  each ingested **PDF** source that produced **no extracted raster media** (its
  `_media/` dir absent/empty), and only when `pdf_render is not None`, render its
  pages to PNGs under the document's `assets/figures/` and append a `FigureEntry`
  per rendered page. The adapter's output names are already deterministic
  (`<pdf-stem>-p<NN>.png`, adapter docstring `:50-53`) and the catalog sorts by
  `id` (`domain/figure_catalog.py:37`) — determinism preserved.
- When the toolchain is absent: no render, no figures, a WARN in the intake
  report (G) naming the missing capability (L) — the document still assembles.

**ADR-F.** *Render only vector-only PDFs, gated on empty raster extraction.*
Rendering every PDF page would duplicate figures opendataloader already
extracts as raster and bloat the catalog non-deterministically w.r.t. toolchain
version. The "zero extracted raster" gate is the precise trigger for the actual
gap (proposal F). Rejected: always-render (wasteful, double-counts), or a CLI
flag (agent shouldn't need to know — auto-detect the vector case).

---

### G. Intake / gap report

**Current:** `ContextService.build_gap_report` (`application/context.py:130`)
already writes a machine-readable `sections/gap-report.json` (context-field gaps
+ section `required_content` gaps, reusing `requirement_present`). Ingest already
writes `inbox/_detection.json` + source manifest + classification queue
(`ingest.py:192-201`). `00-fact-ledger.md` is built by `build-ledger`
(`collection_app.py:58`). None of these is a single human/agent-readable "what I
found / what's missing / how to finish" view (proposal G).

**Design — a derived report, no new data source.**

- New pure renderer `domain/intake_report.py:render_intake_report(detection: dict, manifest: dict, gap_report: dict, ledger_pending: list[str]) -> str`
  producing Markdown with three sections: **Found** (ingested sources + roles +
  figures from `_detection.json`/manifest/figure-catalog), **Missing** (gap-report
  context/section gaps + PENDIENTE ledger lines + WARN'd optional inputs from
  doctor E/L), **How to finish** (an ordered checklist derived from the two
  above — resolve each PENDIENTE, confirm each queued classification, add each
  missing optional input).
- Written at ingest time (`IngestService.ingest_inbox` end, `ingest.py:195`)
  to `inbox/intake-report.md`, and refreshable standalone. It is pure over
  already-produced JSON — a *view*, so it never introduces a second source of
  truth and stays deterministic.

**ADR-G.** *A view over existing artifacts, not a new pipeline stage.* Every
input already exists on disk after ingest + gap-report; the report just joins
them for a human/agent. Rejected: a new service that re-derives gaps (would
duplicate `build_gap_report`'s logic and risk divergence).

---

### H. Build-time figure/table numbering + cross-ref

**Current:** the figure catalog (`domain/figure_catalog.py`), the
`[[figure:fig-<sha8>]]` marker convention, and `resolve_section_figures` (`:41`)
all exist — **but grep confirms no consumer in the assembly/pandoc build path**
(`DocxRendererAdapter.build`, `application/docx_assembly.py:77` reads sections
and calls pandoc directly; the only other references are in `qa.py` and the
audit adapter). The audit adapter (`python_docx_audit_adapter.py:167`
`_check_figure_captions`) merely *warns* if a figure lacks a manual `Figura N.`
caption — i.e. today the author hand-writes both the image and the literal
number (proposal H).

**Design — a pure numbering/cross-ref pass, run at build over ordered sections.**

- Authors write **symbolic labels**, never numbers: a figure marker already
  exists (`[[figure:fig-<sha8>]]`); add a table label marker in the same family
  (`[[table:<slug>]]`) and a caption placeholder + a reference token
  (`[[ref:<slug>]]` rendering to `Ver Figura N`/`Ver Tabla N`). This mirrors the
  existing `[[TOC]]`/`[[figure:]]` convention (`section_rendering.py:34`,
  `figure_catalog.py:7-9`) — **no new syntax family**.
- New pure function `domain/cross_reference.py:number_and_resolve(ordered_sections: list[tuple[str, str]]) -> list[tuple[str, str]]`:
  1. Walk sections in **document order** (the `sorted(config["sections"], key=order)`
     order `build` already computes, `docx_assembly.py:82`), then in-text order.
  2. Assign `Figura 1..N` / `Tabla 1..M` sequentially to each figure/table label
     in first-appearance order; build a `label → number` map.
  3. Rewrite each caption placeholder to `Figura N. <caption>` / `Tabla M. <caption>`
     and each `[[ref:<slug>]]` to `Ver Figura N` / `Ver Tabla M`. A `[[ref:]]` to
     an unknown label resolves to an explicit `Ver Figura ?` + a build WARN
     (never a silent guess — mirrors `resolve_section_figures` returning `None`
     for unknown ids, `figure_catalog.py:44-46`).
- Wire it into `DocxRendererAdapter.build` (`docx_assembly.py:100`), **before**
  `_strip_frontmatter_to_temp`/pandoc: read the ordered section texts, run
  `number_and_resolve`, write the numbered text to the temp dir that already
  feeds pandoc. The function is pure and deterministic → same sections always
  yield the same numbers, preserving the byte-identity golden tests.

**ADR-H.** *Number in document order at build; authors use stable labels
(proposal question 3 → document order).* The number is a *rendering* artifact,
not prose — keeping it out of the `.md` upholds the reproducibility boundary (M):
edit/reorder a section and numbers recompute deterministically with no manual
renumber. Rejected: honoring an author-declared explicit order (adds a config
surface, invites drift, and the proposal's assumed answer is document order);
storing numbers in the catalog (couples numbering to ingest, not render order).

---

### I. `doc status`

**Current:** `doc_app` (`cli/commands/doc_app.py:15`) has
new/list/current/show/use/rename/delete; no status. `ContextService.status`
(`application/context.py:39`) already yields per-topic filled/missing;
`gap-report.json`, `figure-catalog.json`, `_detection.json`, and `output/`
already exist on disk.

**Design.** New `doc status [--json]` command on `doc_app`, backed by a thin
**aggregator** (application method, e.g. `PipelineService.status_summary` or a
new small `StatusService`) that *reads* existing artifacts — introduces no new
state:

- context: `ContextService.status` (filled N/M, which required topics missing),
- sections: count authored `sections/NNN-<id>.md` vs. template sections
  (the same existence check `build` uses, `docx_assembly.py:84-88`) and which
  are still scaffold (contain PENDIENTE),
- ingest: presence/summary of `inbox/_detection.json` + classification queue,
- figures: count from `figure-catalog.json`,
- output: presence/mtime of `output/draft`/`final` artifacts.

`--json` for agent consumption, Markdown for humans (same dual-output pattern as
`doctor`/`review-rules`, `core_app.py:25`, `collection_app.py:40`).

**ADR-I.** *Aggregate-and-read, never persist.* Status is a derived view; a
stored status file would be a second source of truth to keep in sync. Reuses
`ContextService.status` rather than re-deriving.

---

### J. Review false-positive precision

**Current three FP sources:**
- `_check_subjective_terms` (`rules.py:249`) flags any `\bterm\b` with no
  evidence-awareness (but note: `SUBJECTIVE_TERMS` default is now empty,
  `normative.py:19` — terms come from the template's `normative` block, so this
  only fires when a document type declares them).
- `requirement_present` (`rules.py:57`) does substring matching of
  `required_content` keywords — a short keyword can match unintended substrings.
- `review_cross_consistency` contested-stack check (`rules.py:574-587`) flags a
  term like `Firebase` unless the section says `pendiente` or matches the
  `_HEDGE_RE` (`:509`) — so a legitimate, delimited mention still warns
  (`DEFAULT_CONTESTED_STACK_TERMS:511`).

**Design — make each check evidence-aware, TDD with positive + negative
fixtures (proposal risk mitigation):**

- **Contested-stack (`:574`):** suppress the WARN when the term appears
  *adjacent to a delimiting/evidence signal* (a citation, a nearby scope
  qualifier, or an explicit "se usa"/"stack:" declaration), not only when the
  whole section is `pendiente`/hedged. Broaden `_HEDGE_RE` into a precise
  "the mention is qualified" predicate operating on the local window around the
  match, not the whole lowercased body (`:579` currently tests
  `_HEDGE_RE.search(lowered)` over the entire section — a hedge anywhere
  suppresses everywhere; tighten to the match's neighborhood).
- **Required-content (`requirement_present:57`):** require **word-boundary**
  matching for short candidates (the same `\b…\b` fix already applied to the
  PENDIENTE marker, `rules.py:54`), so a 4-letter keyword can't match inside a
  larger word. Keep the `detect` alias escape hatch.
- **Subjective terms (`:249`):** already `\b…\b`; add an evidence-aware
  suppression identical in spirit to the contested-stack fix (a subjective term
  next to a citation/figure reference is substantiated).

Each fix ships with a paired `test_rules.py` fixture: one input that MUST still
flag (regression guard) and one that MUST NOT (the FP that motivated it, e.g.
delimited `Firebase`, `independiente` containing "pendiente" already covered at
`:54`).

**ADR-J.** *Local-window evidence, not global.* The FPs come from
whole-section boolean tests where a signal anywhere suppresses/triggers
everywhere. Scoping each test to the match neighborhood is the root-cause fix
and preserves genuine catches. Rejected: deleting the checks (loses real
value), or a global allowlist (doesn't generalize).

---

### K. Cross-source conflict detection

**Current:** conflicting facts across ingested sources (proposal's bun.js/TS vs.
PHP/Laravel example) are caught only by agent luck. `review_cross_consistency`
(`rules.py:514`) checks consistency *within the authored sections/template*, not
*across ingested raw sources*.

**Design — a deterministic check over ingested source texts, WARN into the
intake report/ledger.**

- New pure function `domain/source_conflict.py:detect_conflicts(sources: list[tuple[str, str]]) -> list[Conflict]`
  where each `Conflict` names the conflicting term-group and the source files it
  disagrees across. First cut: a curated set of **mutually-exclusive term
  groups** (e.g. one stack-family vs. another) — if two ingested sources each
  assert a different member of the same exclusive group, emit a WARN. Reuses the
  same `DEFAULT_CONTESTED_STACK_TERMS` vocabulary spirit (`rules.py:511`),
  extended to exclusive *groups*. Pure, deterministic, sorted output.
- Wired in `IngestService` after the walk (it already has each ingested source's
  text available), surfaced as a WARN block in the intake report (G) and the
  source manifest. Never blocks; never auto-resolves (bound decision 2 —
  fail-open, agent decides).

**ADR-K.** *Deterministic term-group heuristic, not semantic inference.* No LLM
(bound decision 1). A curated exclusive-group table is deterministic and
explainable; false positives are cheap because output is a WARN the agent
adjudicates. Rejected: NLP/embedding similarity (non-deterministic, new heavy
dep, violates bound decision 1).

---

### L. Toolchain validation + optional capabilities

**Current:** `run_doctor` (`application/doctor.py:29`) already checks
`pandoc` (`:95`, currently unconditional), `libreoffice` (`:100`, already
`required=False`), `python`/`python-docx`/`gh`. No declaration of the
figure-render toolchain (opendataloader/java, pypdfium2/pillow, mermaid/node/
Chrome) as optional capabilities.

**Design.** Extend `run_doctor` with a **capability section**:

- **Required:** `uv` (invocation runtime) and `pandoc` (`build-docx` hard
  dependency — make its check `required=True` explicitly; today it's added
  without `required=False`, so it is already required via the default, but the
  detail should name it as required).
- **Optional (WARN + next-step):** figure-render capabilities, each a
  `required=False` check probing import/availability:
  `pypdfium2`+`pillow` (item F path), `opendataloader`/`java` (raster extraction),
  and the future mermaid/node/Chrome path. Each WARN detail states what degrades
  and how to enable it (mirrors the existing `libreoffice` WARN, `doctor.py:100-107`).

Uses the existing `ToolResolverPort` for PATH tools and guarded `import` for
Python libs (same pattern as `python-docx`, `:124-129`). No new port.

**ADR-L.** *Required = "document can't build without it"; optional = "a
capability degrades".* Aligns the doctor with bound decision 2 (fail-open). The
line is drawn at "does `pipeline assemble` produce a document at all" — pandoc
yes, page-render no.

---

### M. Reproducibility boundary

Design principle, stated in §1 above. Ships as: (1) a spec statement in
`openspec/specs/document-pipeline/spec.md`, (2) a paragraph in `AGENTS.md` (B).
No code. It is the invariant every other item is checked against (notably H's
numbering-at-build and A/C/F's deterministic writers).

---

## 3. PR slicing (chained, stacked-to-main, ≤400 lines each)

Mechanical core first (each independently revertable and degrade-safe), guided
layer second. Order reflects dependency, not just the proposal's suggested list.

| # | Slice name | Items | Primary files | Depends on |
|---|-----------|-------|---------------|-----------|
| 1 | **Fail-open doctor + manual auto-detect + toolchain capabilities** | E, L | `application/doctor.py`, `domain/doctor.py` (flags only), tests | — (unblocks real drops first) |
| 2 | **Workspace config + `doc init`** | A | `domain/workspace_config.py` (new), `cli/_shared.py:64`, `cli/commands/doc_app.py`, tests | 1 (init can seed after doctor guidance exists) |
| 3 | **Built-in template provisioning** | C | `src/docs/templates/builtin/` (new package data), `cli/commands/template_app.py`, `pyproject.toml`, tests | 2 (`doc init` calls `template use`) |
| 4 | **Content-probe adapter + content classification** | D | `domain/ports/content_probe_port.py` (new), `infrastructure/ingest/content_probe_adapter.py` (new), `domain/source_role.py:51`, `application/ingest.py`, `cli/_shared.py`, tests | — (probe adapter also reused by 1's auto-detect; land probe port in 1 or here — see risk) |
| 5 | **Wire PDF render adapter into ingest** | F | `application/ingest.py:735`, `cli/_shared.py:110`, tests | 4 (both touch ingest figure-catalog step) |
| 6 | **Build-time figure/table numbering + cross-ref** | H | `domain/cross_reference.py` (new), `domain/figure_catalog.py`, `application/docx_assembly.py:100`, tests | 5 (numbering consumes catalog entries incl. rendered PDF figures) |
| 7 | **Precise/evidence-aware review rules** | J | `domain/rules.py` (`:57`, `:249`, `:574`), tests (paired ±) | — (independent; can land any time) |
| 8 | **Cross-source conflict + intake/gap report** | K, G | `domain/source_conflict.py` (new), `domain/intake_report.py` (new), `application/ingest.py`, tests | 5 (conflict + report read ingest outputs) |
| 9 | **`doc status`** | I | `cli/commands/doc_app.py`, small aggregator in `application/`, tests | 8 (status summarizes intake report + gaps) |
| 10 | **Agent contract (`AGENTS.md` + `docs guide`) + reproducibility principle** | B, M | `AGENTS.md` (new root, force-included), `cli/commands/core_app.py`, `pyproject.toml`, `openspec/specs/document-pipeline/spec.md`, tests | all (documents the finished surface) |

Ten slices rather than nine: G+K genuinely co-locate in ingest (slice 8), and I
depends on that report, so folding I into 8 would blow the ≤400-line budget.
`sdd-tasks` owns final boundaries and per-slice forecasts.

---

## 4. Determinism & edge-case risks

| Risk | Where | Mitigation |
|------|-------|-----------|
| Rendered PDF pages vary across pypdfium2/toolchain versions | F | Catalog sorts by `id` (`figure_catalog.py:37`); adapter names are stable (`:50-53`); pin `pypdfium2`/`pillow` ranges in `pyproject.toml`; render is gated to vector-only PDFs so raster-extraction machines and render machines don't double-count. Golden byte test covers the deterministic-inputs case only. |
| Numbering non-determinism if section/in-text order isn't total | H | `number_and_resolve` numbers in the exact `sorted(sections, key=order)` order `build` already uses (`docx_assembly.py:82`) then first-appearance in text — a total order. Unknown `[[ref:]]` → explicit `?` + WARN, never a silent variable output. |
| Content probe reads differ by platform/locale (byte order, encoding) | D | Case-fold tokens; ASCII byte-order sort (the ingest walk already documents this deliberate choice, `ingest.py:218-225`); probe failures → empty signals (fail-open), so classification degrades to folder-lexicon-only, never errors. |
| Malformed `docs.config.json` bricks every command | A | `build_workspace` best-effort parse; malformed → WARN + ignore, fall back to env/default (fail-open). Covered by a test with a corrupt file. |
| Review-precision fix regresses a genuine catch | J | Each fix ships paired positive+negative fixtures (proposal risk mitigation); characterization tests (`test_rules_characterization.py`) guard existing behavior. |
| Package data not shipped in wheel | B, C | A build+install test asserts `docs guide` and `template list --available` work from the installed wheel, not just the source tree. |
| `ContentProbePort` needed by both slice 1 (E auto-detect) and slice 4 (D) | ordering | Land the port + adapter in whichever slice merges first (recommend slice 1's auto-detect uses a minimal probe, slice 4 extends it) — flagged for `sdd-tasks` to sequence. |
| Fail-open hides a genuinely broken run | E, G | Clearly-marked gaps + intake report + finish-checklist (G); `--strict` restores hard-fail (E). |

## 5. Open questions for `sdd-tasks`/spec

1. Exact `ContentSignals` field set and per-signal weights (D) — bounded by the
   existing `min(1.0, 0.5·folder + 0.3·name)` scheme (`source_role.py:84`);
   weights are a spec detail, not an architecture fork.
2. The curated mutually-exclusive term groups for K — a data table, refine in
   spec/tasks.
3. Whether `docs guide` should support section anchors (`docs guide figures`) —
   deferred; full-print is the lazy sufficient version.
