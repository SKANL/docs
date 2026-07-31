# Proposal: Smart Figure Embedding

## Intent

Relevant ingested images never reach the assembled `.docx`; authors get text-only
documents even when evidence images exist. Sub-project 1 of "document visual
support" makes the harness embed the RIGHT images automatically: a mechanical
role/provenance filter (harness) keeps evidence-role figures and drops
example/reference-role (`guia`) ones, while relevance, placement, and caption stay
an agent cognitive slot. This proves the filter -> stable-path -> embed pipeline
that sub-project 2 (generated visuals) builds on.

## Scope

### In Scope
- Add `source_role` / `origin_kind` to `FigureEntry`; catalog stays a deterministic INVENTORY.
- Mechanical role filter at ingest: keep evidence-role, exclude `guia`/reference-role. Propagate the parent PDF's role to vector page-renders.
- **Stable-asset-path fix**: copy surviving standalone candidates to `assets_dir/figures/` at ingest (today loose evidence images live only in ephemeral `inbox/` — blocker for assemble-time embedding).
- Label -> catalog binding manifest (new), surfaced via **`figure-catalog.json`** (generic figures are NOT queued in `_placement-queue.json`).
- Pandoc-markdown embedding at the label-resolution hook.
- Determinism (byte-identical) + graceful degradation (missing/corrupt image -> WARN+skip, never crash) tests.

### Out of Scope
- **Embedded-raster extraction** (raster media buried inside PDF/DOCX sources, skipped at `ingest.py:951-952`). Deferred to a follow-up — see Risks.
- Sub-project 2 (on-demand generated visuals).
- Agent relevance/placement/caption logic (cognitive slot, unchanged).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `asset-management`: `FigureEntry` gains `source_role`/`origin_kind`; surviving standalone figures copied to `assets_dir/figures/`. Catalog remains inventory.
- `document-render`: new requirement — resolve a symbolic label to its bound catalog figure and emit an embedded image at build time.
- `document-pipeline`: ingest applies the role filter and stable-path copy.

## Approach

Recommended (smaller diff): at the label-resolution hook, emit real
`![caption](path){width=...}` Markdown so **pandoc embeds natively** and the
existing `python_docx_assembly_adapter._transfer_drawing_run` carries the image
through the cover merge. Determinism is already covered — both render paths end in
`normalize_docx_zip_timestamps`. Reuses two working mechanisms vs. new
`add_picture` code. Tradeoff: sizing precision depends on pandoc attribute
fidelity (acceptable; revisit only if sizing proves inadequate).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `domain/figure_catalog.py` | Modified | Add `source_role`/`origin_kind` |
| `application/ingest.py` (~868-988) | Modified | Role filter, role propagation, stable-path copy |
| `domain/cross_reference.py` / new module | New/Modified | Label -> catalog binding |
| `application/section_markdown.py` / `docx_assembly.py` | Modified | Emit `![](){width=}` at label hook |
| `specs/asset-management`, `specs/document-render` | Modified | New requirements |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Ficha evidence is embedded raster (invisible in v1) | Med | **Lean is the recommendation.** Verify how the ficha arrives: if it is a loose image dropped in `inbox/`, v1 embeds it. Only raster buried inside a PDF/DOCX source is deferred — and it feeds the SAME catalog+filter+embed pipeline later with zero rework. Building extraction now (media-dir walk, double-count-vs-vector, role propagation) before the embed path is even proven is the overbuild. |
| Role divergence: raw `classify()` vs human-confirmed role | Low | Prefer confirmed role from `_classification-queue.json` when present |
| Pandoc sizing fidelity | Low | Accept for v1; manual `add_picture` is the fallback |
| No existing embed determinism tests | Med | Add characterization tests (byte-identity + WARN+skip) |

## Rollback Plan

Revert the change branch. New `FigureEntry` fields are additive; the catalog
schema tolerates absence. No migration — catalogs regenerate deterministically at
next ingest.

## Dependencies

- pandoc (already used). No new dependencies.

## Success Criteria

- [ ] Evidence-role standalone images embed in the assembled `.docx`; `guia`/reference-role images do not.
- [ ] Surviving candidates exist under `assets_dir/figures/` after ingest.
- [ ] Build is byte-identical across runs; missing/corrupt image -> WARN+skip, no crash.
- [ ] Candidates surface via `figure-catalog.json` (not the placement queue).
