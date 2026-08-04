# Explore: on-demand-visual-generation

Sub-project 2 of "document visual support" (Sub-project 1 = smart-figure-embedding,
archived at `openspec/changes/archive/2026-07-31-smart-figure-embedding/`).
Artifact store: hybrid. Engram mirror: `sdd/on-demand-visual-generation/explore`.
Materialized on disk by the orchestrator (the sdd-explore sub-agent had no Write tool).

## 1. KEY FEASIBILITY — can .docx embed SVG via pandoc? NO, not reliably.

Confirmed against upstream pandoc issue jgm/pandoc#9195: pandoc's docx writer
places raw SVG bytes in the media part but never emits the OOXML
`mc:AlternateContent`/`a14:svgBlip` fallback Word requires → Word shows "the
picture can't be displayed". PNG/JPEG embed fine. HTML output is fine:
`html_render.py:83` passes `--embed-resources`, base64-inlining SVG as a `data:`
URI that browsers render natively.

**Consequence**: the docx path needs SVG rasterized to PNG before embedding; the
HTML path can keep SVG. Two-artifact-per-visual (or conditional rasterize) to
resolve in propose/design.

### Pre-existing gap: standalone SVG ingest is already silently broken
`.svg` is in `_IMAGE_EXTENSIONS` (`ingest.py:85`) so a dropped `.svg` is a figure
candidate, but `PythonDocxImageMetadataAdapter.read_dimensions` (python-docx's
raster-only parser) raises `UnrecognizedImageError` → null dims → the ADR-6
resolver guard excludes it. So an ingested SVG is unusable end-to-end today.
Propose decides whether fixing this is in scope (cheap — generate-visuals needs
SVG-dimension handling anyway).

## 2. Sub-project 1 foundation to plug into
- `FigureEntry` (`domain/figure_catalog.py:8`): sha256, width_px, height_px,
  origin_relative_path, caption, source_role, origin_kind. `origin_kind="generated"`
  is a natural third value (today: standalone / pdf_render).
- `build()` sorts by `id=fig-<sha8>` → `figure-catalog.json`, deterministic.
- `_build_figure_catalog` (`ingest.py:911`) is ingest-scoped and FULLY OVERWRITES
  the catalog each run (`ingest.py:961`, no merge). A separate generate-visuals
  stage needs a deterministic read-merge-write (re-sort by id) or a shared
  catalog-merge helper.
- `BoundFigure`/`figure_image_markdown` (`domain/figure_binding.py`) emit
  `![Figura N. caption](abs-path){width=Xin}` — a generated PNG under
  `assets_dir/figures/` with valid dims + a binding plugs in with ZERO new
  binding-syntax work.
- `build_bound_figures_resolver` (`application/figure_resolver.py:29`) fails open,
  WARNs+skips on missing dims/file. A generated entry must satisfy: non-null
  width/height (from the renderer's known canvas size — SVG has no raster dims)
  + a real file at `assets_dir/figures/<name>`.
- Both `docx_assembly.py:78` and `html_render.py:64` call the SAME resolver — no
  new call site; a generated+cataloged+bound visual is picked up automatically.

## 3. Pipeline stage wiring
- `domain/pipeline.py`: `_INGEST_STAGES` (line 26) format-agnostic constants;
  `pipeline_stage_plan` composes prep+assemble. A `generate-visuals` stage is the
  same shape — must run AFTER ingest (catalog exists to merge) and BEFORE
  assemble (resolver sees generated entries). Ordering vs `build-sections`
  (agents referencing generated labels while drafting) is a propose decision.
- Stage callable in `PipelineService._stage_callables` (`pipeline.py:175`),
  shape of `stage_ingest` (line 306); per-visual failure WARNs+skips (like
  `stage_collect_issues` "omitido:" line 216), never fails the whole stage.

## 4. Composition root (`cli/_shared.py`)
- Mirror `self.renderers: dict[str, DocumentRendererPort]` (line 130) keyed by
  output_format → `self.visual_renderers: dict[str, VisualRendererPort]` keyed by
  visual `type` ("mermaid"/"chart"). `resolve_renderer` (line 222) raises on
  unknown — mirror it. `ingest_handlers: dict[str, SourceIngestPort]` by `kind`
  (line 148) is the closest by-type precedent.
- Optional-toolchain guarded import (lines 159-164, pypdfium2 try/except→None);
  mermaid/chart renderers follow the same guarded construction so `Deps()` never
  crashes when a toolchain is absent; degrade-to-None+WARN at render time
  (mirrors `_render_vector_pdf_figures` `self.pdf_render is None`, `ingest.py:1025`).

## 5. Toolchain / determinism
- NO SVG charting lib or SVG rasterizer is a dependency today (deps: defusedxml,
  docxcompose, filetype, opendataloader-pdf, pillow, pydantic, pypdfium2,
  python-docx, typer). pypdfium2 renders PDF pages only, not SVG.
- **Chart**: matplotlib (SVG backend) is the standard pure-Python choice — NEW
  dep; SVG determinism unverified (font hinting / random ids) — needs a spike +
  normalization (`svg.hashsalt`, font config) analogous to
  `deterministic_zip.normalize_docx_zip_timestamps`.
- **Mermaid**: official `mermaid-cli` (`mmdc`) ALWAYS launches headless Chromium
  via Puppeteer, even for SVG — this IS the Chrome-headless problem the design
  wants to avoid, so official mermaid-cli is disqualified as the default.
  Chrome-free alternatives: `mermaidx` (PyPI, QuickJS+resvg) and `mmdr` (Rust) —
  unvetted/newer, need a propose spike.
- Mermaid SVG non-determinism: auto-generated element ids (`mermaid-svg-<random>`),
  possibly inlined fonts — a normalization pass (rewrite ids to a stable
  order-keyed scheme, strip wall-clock) before hashing into `sha256`.
- Fail-open convention to reuse: `doctor.py:_capability_checks` (line 203,
  Check(required=False) + install guidance); `PdfRendererAdapter.build`
  (`pdf_render.py:36`) WARNs+returns None on toolchain RuntimeError.

## 6. Agent visual-spec format
Recommendation for propose: `sections_dir/visual-specs.json`, agent-authored,
`{"label", "type": "mermaid"|"chart", "source": <inline or path>, "caption"}` —
`type` dispatches to the VisualRendererPort registry like `kind` dispatches
`ingest_handlers`. Fail-open on malformed/missing; WARN+skip per-entry. Decide
auto-bind (generate populates figure-bindings.json for its labels) vs
agent-must-bind (Sub-project 1's agent-does-the-binding philosophy).

## Risks / open questions for propose/design
1. **Docx SVG embedding is a hard blocker** → rasterize-to-PNG-for-docx decision
   (dual-artifact per visual vs PNG-only). Affects the catalog model: does a
   generated visual need TWO entries (SVG+PNG) or one with format-aware path
   resolution? Current resolver assumes one file per catalog id.
2. **Official mermaid-cli reintroduces headless-Chrome** — toolchain choice is
   design-blocking; mermaidx/mmdr unvetted (spike or documented risk acceptance).
3. **SVG dimension extraction has no port** — dims come from the renderer at
   generation time, not a post-hoc reader.
4. **matplotlib SVG determinism unverified** — spike in propose.
5. **Catalog merge**: ingest overwrites figure-catalog.json — generate-visuals
   needs a merge contract to avoid clobbering.
6. **Standalone-SVG-ingest already broken** — in scope to fix or explicitly defer.

## Docx-embedding approaches
- **A (recommended)**: rasterize SVG→PNG for docx, keep SVG for HTML. Deterministic
  if rasterizer pinned; each format gets its best asset. Cons: two artifacts,
  per-format path resolution, a rasterizer dep (resvg/cairosvg). Effort: Medium.
- **B**: rasterize to PNG universally (SVG transient). Single artifact, no catalog
  change. Cons: loses SVG as a first-class deliverable; worse print/zoom. Effort: Low.
- **C**: embed SVG raw in docx anyway — DISQUALIFIED (broken in Word, pandoc#9195).

## Next: sdd-propose (resolve the docx-raster approach + mermaid toolchain + catalog merge).
