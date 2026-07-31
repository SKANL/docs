# Design: Smart Figure Embedding

Sub-project 1 of "document visual support". Artifact store: hybrid. Engram mirror:
topic_key `sdd/smart-figure-embedding/design`.

## 1. Context & constraints

- Hexagonal: `cli -> application -> domain`; `infrastructure` implements domain
  ports. New pure logic lives in `domain/`; I/O and wiring stay in
  `application/`/`infrastructure/`. No domain module imports infrastructure.
- Determinism is a product requirement: same inputs -> byte-identical outputs.
  Both render paths already end in `normalize_docx_zip_timestamps`
  (`python_docx_assembly_adapter.py:386,595,615`), so embedding via pandoc adds
  no new determinism surface as long as we introduce no wall-clock/random data.
- Graceful degradation is the house posture (`ingest.py:_read_image_dimensions`,
  `_ingest_one_safely`): a missing/corrupt input WARNs (with cause) and skips,
  never aborts the batch/build.
- CLI-facing strings Spanish; code/comments/docs English.

Approved LEAN scope (from proposal): embed only what is catalogable today —
standalone user images + vector PDF page-renders. Embedded-raster extraction
stays deferred; it feeds the SAME catalog+filter+embed pipeline later with zero
rework.

## 2. Architecture overview (data flow)

```
INGEST (application/ingest.py, assets_dir known)
  _build_figure_catalog
    standalone image candidates ─┐
    _render_vector_pdf_figures ──┤─> FigureEntry{ sha256, dims, origin, source_role, origin_kind }
                                 │
    [pure] should_catalog_figure(role, dims, MIN_DIM)  ── drops normative/example + sub-threshold junk
                                 │
    surviving standalone ── atomic copy ──> assets_dir/figures/fig-<sha8><ext>
    (vector renders already there; not re-copied)
                                 │
    build_figure_catalog(...) ──> sections/figure-catalog.json   (deterministic INVENTORY)

AGENT (cognitive slot, hand/agent-authored)
    sections/figure-bindings.json   { "<label>": "fig-<sha8>" }

ASSEMBLE (application/docx_assembly.py + html_render.py -> section_markdown.py)
    load catalog + bindings + assets_dir ──> resolve label -> BoundFigure (validated: exists + non-null dims)
    strip_frontmatter_to_temp(sections, bound_figures=...)
      [pure] number_and_resolve(..., bound_figures)
         bound   [[figure:label]] -> ![Figura N. caption](abs-path){width=Win}   (pandoc embeds)
         unbound [[figure:label]] -> Figura N.                                    (unchanged text path)
    render_pandoc -> _transfer_drawing_run carries image through cover merge
    normalize_docx_zip_timestamps -> byte-identical
```

## 3. Component map

| Layer | File | Change |
|-------|------|--------|
| domain | `domain/figure_catalog.py` | `FigureEntry` gains `source_role`/`origin_kind`; `build()` emits them |
| domain | `domain/figure_filter.py` (**new**) | pure `should_catalog_figure(...)` + `MIN_FIGURE_DIMENSION_PX` |
| domain | `domain/figure_binding.py` (**new**) | `BoundFigure` dataclass + pure `figure_image_markdown(...)`/`figure_width_attr(...)` |
| domain | `domain/cross_reference.py` | `number_and_resolve(..., bound_figures=None)` emits image markdown for bound labels |
| application | `application/ingest.py` | role resolution, mechanical filter, stable-path copy, `origin_kind`/`source_role` on both catalog sources |
| application | `application/section_markdown.py` | `strip_frontmatter_to_temp(sections, bound_figures=None)` threads resolver to the pure pass |
| application | `application/docx_assembly.py` / `application/html_render.py` | build the `label -> BoundFigure` resolver (read catalog+bindings, validate) and pass it down |
| infra | (none new) | reuses `_transfer_drawing_run`, `render_pandoc`, `normalize_docx_zip_timestamps` |
| specs | `specs/asset-management`, `specs/document-render`, `specs/document-pipeline` | delta requirements (tasks phase) |

## 4. Decisions (ADR-style)

### ADR-1 — `FigureEntry` role/provenance fields

Add two `str` fields to the frozen dataclass (`domain/figure_catalog.py:8`):

- `source_role: str` — resolved effective role: one of `evidence` / `normative`
  / `example` / `unknown` (the vocabulary `source_role.classify` already
  returns; `ROLES`/`_VALID_ROLES` is the single source of truth).
- `origin_kind: str` — provenance of the catalog row: `"standalone"` (loose
  user image) or `"pdf_render"` (vector page render). Drives the
  no-double-copy rule (ADR-3) and keeps the two disjoint catalog sources
  self-describing.

`build()` (`figure_catalog.py:16`) adds both keys to each row. Additive and
default-valued (`source_role=""`, `origin_kind=""`) so the catalog schema
tolerates absence and old catalogs regenerate deterministically (proposal
rollback plan). Existing `caption` field stays.

**Role resolution rule (resolves the role-divergence risk).** A single pure
lookup used for BOTH catalog sources:

```
effective_role(rel) = confirmed_roles.get(rel)  if present and valid
                       else classify(rel).role
```

- `confirmed_roles` = `self._read_prior_confirmed_roles(inbox_dir)` — the
  already-existing reader of `_classification-queue.json` (`ingest.py:584`),
  which already validates roles against `_VALID_ROLES` and WARNs on garbage.
  Reused verbatim; no new queue plumbing.
- **Standalone image**: `rel` = the image's inbox `origin_relative_path`.
  Standalone images are `heuristic_candidates`, excluded from `sources`, so they
  are not in the queue today — the lookup falls through to `classify(rel)`.
  The rule is still uniform, so a future human-confirmed image role is honored
  for free.
- **Vector PDF render**: `rel` = the **parent PDF's** inbox `relative_path`
  (in scope at `_render_vector_pdf_figures`, `ingest.py:948,963`). The PDF is a
  real source, so its human-confirmed role (if any) wins over raw
  `classify()` — this is exactly the divergence case, resolved in favor of the
  human confirmation. Every page-render inherits the parent's role.

Rationale: confirmed role is a human/agent decision recorded at the harness's
one confirmation interface; raw `classify()` is a heuristic. Preferring the
confirmed value is consistent with `_resolve_role_gate` (`ingest.py:558`),
which already lets a confirmed role override in any mode.

### ADR-2 — Mechanical filter (pure domain predicate)

New pure module `domain/figure_filter.py`:

```python
MIN_FIGURE_DIMENSION_PX = 100  # ponytail: constant now; promote to workspace config if a doc needs a different floor

def should_catalog_figure(source_role: str, width_px: int | None, height_px: int | None) -> bool:
    if source_role in {"normative", "example"}:   # guia/reference-role -> drop
        return False
    if width_px is not None and height_px is not None and max(width_px, height_px) < MIN_FIGURE_DIMENSION_PX:
        return False                               # sub-threshold junk (icons, bullets, rules)
    return True                                    # evidence + unknown (user-dropped), keep
```

- **Keeps** `evidence` and `unknown`. `guia` folds to `normative` in
  `NORMATIVE_LEXICON` (`source_role.py:31`) and is dropped; `example`/reference
  dropped. `unknown` = a user image with no folder signal is kept (fail-open) —
  the catalog is an INVENTORY, and the real embed gate is the agent binding a
  label (ADR-4), so leniency here costs nothing while a wrongly-dropped user
  ficha would be unrecoverable.
- **Where it runs**: inside `_build_figure_catalog` (`ingest.py:868`), applied
  to each candidate AFTER `source_role`/dims are computed and BEFORE the entry
  is appended and before the stable-path copy (ADR-3). Dropped candidates never
  enter the catalog and are never copied.
- Null dims cannot be judged for size -> fail-open keep (but a null-dims figure
  can never embed, per ADR-6, so it is inert until re-dimensioned).
- Pure, no I/O, deterministic — trivially unit-testable; the filter is the
  smallest well-bounded unit and carries the behavior-first tests.

### ADR-3 — Stable-asset-path copy

Surviving **standalone** candidates are copied to `assets_dir/figures/` at
ingest so a later `assemble` stage (inbox gone) can resolve them.

- **Deterministic name**: `fig-<sha8><ext>` where `<sha8>` = `sha256[:8]` (same
  token the catalog `id` uses) and `<ext>` = lower-cased origin suffix. Stable,
  collision-safe, and makes `catalog id -> asset filename` mechanical.
- **Atomic write**: extend `_copy_asset` (`ingest.py:847`) to temp-then-
  `os.replace`, matching the established temp-then-atomic-rename convention
  (`atomic_ingest_write.py`, `filesystem_ingest_artifact_writer.py`) so a
  failure never leaves a partial file a later run would accept. (Declared-asset
  copies reuse the same hardened helper — a free robustness win.)
- **No double-copy of vector renders**: `_render_vector_pdf_figures` already
  writes page-renders straight into `assets_dir/figures/` (`ingest.py:964`).
  Those rows carry `origin_kind="pdf_render"`; the copy step runs only for
  `origin_kind="standalone"`.
- **Path normalization**: after copying a standalone survivor, set its
  `origin_relative_path = "assets/figures/fig-<sha8><ext>"` (POSIX). Vector
  renders already store `assets/figures/<name>`. Result: EVERY catalog row
  points at a stable, doc-root-relative path, so assemble resolves both kinds
  uniformly as `Path(assets_dir) / "figures" / Path(origin_relative_path).name`
  (`assets_dir` = `config["paths"]["assets_dir"]`, `cli/_shared.py:322`).
  `source_role`/dims are computed from the ORIGINAL inbox `rel` before this
  rewrite, so classification signal is not lost.

### ADR-4 — Label -> catalog binding manifest

- **File**: `sections/figure-bindings.json` (sibling of `figure-catalog.json`,
  same `sections_dir`).
- **Schema** (minimal, deterministic): `{ "schema": 1, "bindings": { "<label>": "fig-<sha8>" } }`
  — author-chosen symbolic label -> catalog figure `id`. Nothing else; relevance
  is expressed purely by the existence of a binding.
- **Who writes it**: the **agent** (cognitive slot). Binding a label to a
  catalog id IS the relevance/placement decision the harness deliberately does
  not make. Hand-editable JSON; no new CLI required for v1 (a thin
  `docx bind-figure` command is a later convenience, not in scope).
- **Who reads it**: **assembly** (`docx_assembly.build` / `html_render.build`),
  which joins it against `figure-catalog.json` to build the
  `label -> BoundFigure` resolver.
- Absent/malformed file -> `{}` bindings (same fail-open JSON read as
  `_read_prior_confirmed_roles`); every `[[figure:label]]` then takes the
  unchanged text-only path.

### ADR-5 — Embedding via pandoc-markdown (recommended approach)

New pure `domain/figure_binding.py`:

```python
ASSUMED_DPI = 96
MAX_CONTENT_WIDTH_IN = 6.0  # ponytail: letter/A4 body width minus margins; config later

@dataclass(frozen=True)
class BoundFigure:
    label: str
    catalog_id: str
    path: str          # absolute, resolved by the application resolver
    width_px: int | None
    height_px: int | None
    caption: str

def figure_width_attr(width_px: int | None) -> str:
    if width_px is None: return ""
    inches = min(MAX_CONTENT_WIDTH_IN, round(width_px / ASSUMED_DPI, 2))
    return f"{{width={inches}in}}"

def figure_image_markdown(number: int, fig: BoundFigure) -> str:
    caption = f"Figura {number}. {fig.caption}".rstrip()
    return f"![{caption}]({fig.path}){figure_width_attr(fig.width_px)}"
```

- **Hook**: `number_and_resolve` (`domain/cross_reference.py:15`) gains an
  optional `bound_figures: dict[str, BoundFigure] | None = None`. In `_rewrite`,
  a `[[figure:label]]` where `label in bound_figures` is replaced by
  `figure_image_markdown(number, fig)`; otherwise the unchanged `Figura N.`
  text. `[[table:]]`/`[[ref:]]` untouched. Default `None` reproduces today's
  byte-for-byte behavior (regression guard for every existing caller).
- `strip_frontmatter_to_temp` (`section_markdown.py:27`) gains the same optional
  `bound_figures` param and forwards it. The application builders
  (`docx_assembly.build:93`, `html_render.build:60`) construct the resolver and
  pass it; passing nothing = current behavior.
- **Sizing**: derived purely from catalog `width_px` (px/96in), clamped to
  `MAX_CONTENT_WIDTH_IN`. Pure function of catalog data + constants — no page
  layout probing, fully deterministic.
- **Path in markdown**: ABSOLUTE path to `assets_dir/figures/<name>`. The
  absolute path is only pandoc's read handle; pandoc embeds the image BYTES into
  the docx, so the machine-specific path never enters the output — determinism
  of output bytes is unaffected.
- **Carry-through**: pandoc emits `<w:drawing>` in the body docx; the existing
  `_transfer_drawing_run` (`python_docx_assembly_adapter.py:252`) already
  deep-copies drawing runs and re-embeds image parts across the cover+body
  merge. No change there. Final `normalize_docx_zip_timestamps` keeps bytes
  identical.
- **Authoring convention** (documented, not enforced): a `[[figure:label]]`
  alone on its paragraph becomes a pandoc implicit-figure with the alt as
  caption; inline usage still embeds but without figure semantics. ponytail: no
  paragraph-detection logic — document the convention.

Rejected alternative — **manual python-docx `add_picture` post-process**: full
programmatic sizing control, but duplicates the pandoc+`_transfer_drawing_run`
capability already in the codebase (more new infra code, second embed path to
keep deterministic). Chosen only if pandoc attribute sizing proves inadequate
(proposal fallback).

### ADR-6 — Graceful degradation

The `label -> BoundFigure` resolver (application, assemble-time) admits a
binding only if BOTH hold:

1. `Path(assets_dir)/"figures"/name` **exists**, AND
2. the catalog row has **non-null `width_px`/`height_px`** (proof the image
   parsed cleanly at ingest — reusing the ingest-time dimension read as the
   readability signal, no new port dependency in the renderer).

Otherwise: `WARN` to stderr naming the label, catalog id, and cause
(`imagen no encontrada` / `sin dimensiones`), and the label is left OUT of the
resolver -> the pure pass falls to the text-only `Figura N.` path. A bound label
therefore NEVER crashes the build; worst case is a numbered caption with no
image — consistent with the hardened ingest/exit-code posture.

Residual (low) risk: an image that dimensioned fine at ingest but is corrupted
on disk afterward would still reach pandoc (`render_pandoc` uses `check=True`).
Judged negligible for v1; the escalation path is the ADR-5 manual-`add_picture`
fallback or a pre-flight probe via `ImageMetadataPort`. Noted, not built.

### ADR-7 — Test strategy (behavior-first, TDD slices)

Strict TDD: each behavior gets a failing test first. Slices kept ≤ ~300 lines
for the review budget.

| Slice | Tests (behavior-first) | ~lines |
|-------|------------------------|--------|
| **S1 — domain filter + fields** | `should_catalog_figure`: drops `guia`/`normative` + `example`, keeps `evidence`, keeps `unknown`, drops sub-threshold (`max(dim) < MIN`), keeps null-dims; `FigureEntry`/`build()` round-trip `source_role`/`origin_kind` | ~120 |
| **S2 — ingest wiring** | `_build_figure_catalog`: guia image excluded / evidence kept; survivor copied to `assets_dir/figures/fig-<sha8>.ext` (atomic); vector render NOT re-copied (`origin_kind=pdf_render`); `origin_relative_path` rewritten to stable path; parent-PDF confirmed role propagated to page-renders over raw `classify()` | ~250 |
| **S3 — binding model + numbering** | `figure_width_attr`/`figure_image_markdown` sizing + clamp; `number_and_resolve` with `bound_figures`: bound label -> `![Figura N. ...](path){width=}`, unbound -> `Figura N.` text; `bound_figures=None` byte-identical to today | ~200 |
| **S4 — assembly + degradation + determinism** | integration: bound label -> assembled `.docx` HAS the image part (assert `word/media/` / a `<w:drawing>` blip); unbound -> no image, text caption only; missing/corrupt bound image -> `WARN` + caption-only, no crash; **byte-identical rebuild**; `estadia` characterization stays green | ~300 |

Rough forecast: **4 PRs / ~870 lines** of tests+code, no slice over the budget.

## 5. Determinism & hexagonal notes

- All new decision logic (`figure_filter`, `figure_binding`, the
  `number_and_resolve` branch) is **pure domain** — no I/O, no clock, no random,
  sorted/total-ordered. Catalog rows already sort by `id` (`figure_catalog.py:32`).
- All new I/O (stable copy, bindings/catalog reads, resolver build) is in
  **application**, reusing existing atomic-write and fail-open-JSON patterns.
- No new infrastructure adapter and no new port: embedding rides the existing
  pandoc + `_transfer_drawing_run` + `normalize_docx_zip_timestamps` path.
- Dependency direction preserved: `cli -> application -> domain`; nothing in
  `domain`/`application` imports `infrastructure`.

## 6. Open questions / assumptions (for spec/tasks/apply)

- **assets_dir at assemble**: assumed `config["paths"]["assets_dir"]`
  (`cli/_shared.py:322`); confirm this key is populated in the assemble config
  the renderers receive (else resolve via `AssetService.workspace.assets_dir`).
- **BitEngine ficha arrival**: if the ficha is a loose image dropped in
  `inbox/`, v1 embeds it; if it is raster buried inside a PDF/DOCX, it is the
  deferred embedded-raster case (out of scope) — verify how it arrives.
- `MIN_FIGURE_DIMENSION_PX=100`, `MAX_CONTENT_WIDTH_IN=6.0`, `ASSUMED_DPI=96`
  are constants now; promote to workspace config only if a real doc needs it.
