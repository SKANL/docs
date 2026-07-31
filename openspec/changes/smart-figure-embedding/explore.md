# Exploration: smart-figure-embedding

Sub-project 1 of a 2-part "document visual support" decomposition (sub-project
2 = on-demand generated visuals, designed later on this foundation).

Artifact store: hybrid. Mirror: Engram topic_key `sdd/smart-figure-embedding/explore`.
Materialized on disk by the orchestrator (the sdd-explore sub-agent had no Write tool this session).

## Goal (approved design, from collaborative brainstorming)

Embed RELEVANT ingested images into the assembled `.docx`. Mechanical
role/provenance filter (harness) + agent-decided relevance/placement/caption
(cognitive slot).

## Current state (file:line evidence)

- `src/docs/domain/figure_catalog.py:8` — `FigureEntry` has NO `source_role` /
  `origin_kind` fields yet (records only `sha256`, `width_px`, `height_px`,
  `origin_relative_path`).
- `src/docs/application/ingest.py:868` `_build_figure_catalog` sources figures
  from two disjoint paths:
  - (a) loose declared/heuristic image files under `inbox/` —
    `origin_relative_path` keeps full folder context, so
    `source_role.classify()` (`src/docs/domain/source_role.py:90`) can be called
    directly on it. **Mechanical role filter is feasible here.**
  - (b) `_render_vector_pdf_figures` (ingest.py:930) — whole-page renders for
    PDFs, output path flattened to `assets/figures/...` (loses folder signal),
    but the source PDF's own `relative_path` is still in scope at line 948, so
    the parent source's role can be propagated.
- `src/docs/domain/cross_reference.py:15` `number_and_resolve` is pure text
  substitution with NO link to the figure catalog (labels are author-chosen,
  "not catalog sha8 ids"). The label→image binding manifest is genuinely new.
- `src/docs/infrastructure/docx/python_docx_assembly_adapter.py:246-268`
  (`_run_has_drawing` / `_transfer_drawing_run`) ALREADY carries embedded
  `<w:drawing>` images across the cover+body merge. Both `render_pandoc` and
  `PythonDocxAssemblyAdapter.assemble` end in `normalize_docx_zip_timestamps`,
  so determinism is already covered for either embedding approach.

## Key findings that refine the approved design

1. **The `_placement-queue.json` assumption was WRONG.** `ingest.py:808-809`
   explicitly SKIPS queueing generic figures ("it is a figure ... not a
   document-structure asset"); they already land only in `figure-catalog.json`.
   → Candidates surface via the **figure catalog**, not the placement queue.
2. **Stable-asset-path GAP (blocker).** Only vector-rendered PDF figures are
   copied to the stable per-doc `assets_dir` (`cli/_shared.py:322`). Ordinary
   loose evidence images are read straight from ephemeral `inbox/` and never
   copied anywhere stable. Embedding at a later `assemble` stage is BLOCKED
   until surviving candidates are copied to `assets_dir/figures/` at ingest.
3. **Uncataloged embedded raster media (scope risk).** Pandoc/opendataloader
   raster media embedded inside a DOCX/PDF lands in `<stem>-<kind>-<sha8>_media/`
   and is explicitly skipped at ingest.py:951-952 (avoids double-counting with
   vector rendering). If "BitEngine ficha" evidence images are embedded raster,
   they are currently INVISIBLE to the harness → scope must grow beyond a filter
   if those must embed.
4. **Smaller-diff embedding path exists (ponytail).** Instead of the assumed
   manual `add_picture`, emit real `![caption](path){width=...}` Markdown at the
   label-resolution hook → pandoc embeds natively, and the existing
   `_transfer_drawing_run` carries it through the cover merge. Materially smaller
   diff; determinism already covered. Recommended default unless sizing precision
   rules it out.

## Hook points

- `src/docs/domain/figure_catalog.py` — add `source_role` / `origin_kind`.
- `src/docs/application/ingest.py:868-988` — role filter, propagate parent-source
  role for PDF-rendered figures, copy surviving standalone candidates to
  `assets_dir/figures/`.
- `src/docs/domain/cross_reference.py` / new domain module — label→catalog binding.
- `src/docs/application/section_markdown.py:27` (`strip_frontmatter_to_temp`,
  numbers markers before pandoc) + `src/docs/application/docx_assembly.py:76-97`
  — embedding hook point.
- `openspec/specs/asset-management/spec.md`, `openspec/specs/document-render/spec.md`
  — new requirement (neither currently specifies image embedding).

## Approaches (for design phase to decide)

1. **Pandoc-markdown embedding** — emit `![caption](path){width=...}` at the
   label hook; pandoc embeds; reuse `_transfer_drawing_run`. Pros: smallest diff,
   reuses two working mechanisms, determinism covered. Cons: sizing precision via
   pandoc attribute fidelity. Effort: Low-Medium. **Recommended default.**
2. **Manual python-docx `add_picture` post-process** — insert pictures into
   `body_docx` before cover-merge. Pros: full programmatic control. Cons: more
   new code, duplicates pandoc+transfer capability. Effort: Medium-High.

## Risks / unknowns for propose+design

- Stable-asset-path gap must be fixed first (copy survivors to `assets_dir/figures/`).
- Uncataloged embedded raster media — scope decision if ficha images are raster.
- Role-confirmation consistency: raw `classify()` vs a human-confirmed role in
  `_classification-queue.json` for the same source could diverge.
- No existing image-embedding correctness/determinism tests — new characterization
  tests required.
- Embedding approach (pandoc vs manual) deferred to design.

## Ready for proposal: yes (with the above flagged).
