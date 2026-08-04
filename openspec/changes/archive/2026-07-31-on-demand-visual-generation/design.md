# Design: On-Demand Visual Generation

## Technical Approach

Extend Sub-project 1's figure foundation with a `VisualRendererPort` registry
(keyed by visual `type`, mirroring `ingest_handlers` by `kind`) plus a
`generate-visuals` pipeline stage that runs after ingest and before assemble.
Per visual: `render → SVG text → normalize_svg (domain, pure) → write .svg →
resvg → .png → dims → FigureEntry(origin_kind="generated") → merge into
figure-catalog.json → auto-bind into figure-bindings.json`. Docx embeds the PNG
(catalog `origin_relative_path`); HTML swaps the sibling `.svg` locally in
`html_render`. Every new boundary fails open (WARN+skip per visual), preserving
the "same inputs → byte-identical outputs" invariant same-machine.

Grounded in: `figure_catalog.py:18` (`build`, sort-by-id), `figure_resolver.py:29`
(non-null-dims + file-exists guard), `pipeline.py:306/212` (stage shape,
`"omitido:"` degrade), `_shared.py:130/159` (`renderers` registry, pypdfium2
`try/except→None`), `pdf_render.py:36` and `ingest.py:1025` (fail-open WARN+None),
`deterministic_zip.py:60` (normalization-as-last-step precedent).

## Architecture Decisions

### Decision: normalize_svg lives in domain, called by the stage (not the port)

**Choice**: `VisualRendererPort.render(spec) -> str` returns RAW SVG text; the
stage calls pure `domain/svg_normalize.py:normalize_svg(text)` before hashing/
writing. Renderers set only their own determinism knobs.
**Alternatives**: renderer returns normalized SVG (duplicates the pass per
adapter); ElementTree reserialize (namespace-prefix churn).
**Rationale**: one shared pure normalizer (DRY, testable in isolation, mirrors
`normalize_docx_zip_timestamps` as a final deterministic pass); minimal port.

### Decision: resvg + dims behind ports, optional-toolchain guarded

**Choice**: `SvgRasterizerPort.rasterize(svg, png)` (resvg CLI adapter,
PATH-resolved via `ToolResolverPort.resolve_resvg`, fail-open). PNG dims via the
EXISTING `ImageMetadataPort.read_dimensions` (python-docx reads PNG) — reused
exactly as `ingest._render_vector_pdf_figures` does (`ingest.py:1049`).
**Alternatives**: cairosvg (Cairo/fontconfig cross-env drift — proposal
Decision 2); new pillow call (redundant port).
**Rationale**: Chrome-free, deterministic, font-dir pinnable; zero new dims port.

### Decision: content-addressed sibling stem, catalog id from PNG

**Choice**: write `assets/figures/<stem>.svg` + `<stem>.png`, `stem =
visual-<sha8-of-normalized-svg>` (known before rasterize, deterministic).
Catalog `sha256 = sha256(png-bytes)`, `id = fig-<png_sha8>`,
`origin_relative_path = assets/figures/<stem>.png`.
**Rationale**: stem shared by both artifacts → HTML `.png→.svg` swap is a pure
filename edit; PNG-hash id keeps the existing resolver/binding contract intact.

### Decision: pure merge + pure merge_bindings, no-clobber

**Choice**: `domain/figure_catalog.py:merge(existing_catalog, generated)` — union
by id (EXISTING wins on collision → generated never clobbers ingest), re-sort by
id. `domain/figure_binding.py:merge_bindings(existing, additions)` — add
`label→id` only when label absent, sorted-key output. I/O stays in the stage.
**Rationale**: matches `build()`'s determinism; behavior-first unit-testable.

### Decision: generate-visuals is a format-agnostic stage before assemble

**Choice**: `_GENERATE_VISUALS = [("generate-visuals", False)]` in
`domain/pipeline.py`; prepended to the assemble stages for both `assemble` and
`all` (`all` = prep + review-document + generate-visuals + assemble). `fail_fast=
False` — a failing visual never blocks the build.
**Alternatives**: put it in `_PREP_STAGES` (runs before ingest → no catalog to
merge) or in `_INGEST_STAGES` (`all` excludes ingest by design).
**Rationale**: catalog exists (ingest ran) and the resolver (build-docx/html)
sees generated entries. Absent `visual-specs.json` → no-op (rollback-safe).

### Decision: chart spec is DECLARATIVE data, never executed code

**Choice**: `ChartSvgRenderer` accepts a structured `source` (JSON: chart kind +
series/labels), never `eval`/`exec`. Mermaid `source` written to a temp file
passed to `mmdc`. `source`-as-path resolves under the doc workspace only.
**Rationale**: agent-authored specs are an untrusted trust boundary (see Threat
Matrix). No code path turns spec text into executable Python/shell.

## Data Flow

    visual-specs.json ─┐
                       ▼
      generate-visuals stage (application/generate_visuals.py)
        │  for each VisualSpec:
        │   renderers[type].render(spec) ─► raw SVG ─► normalize_svg (domain)
        │        │ mmdc absent / bad spec / unknown type → WARN+skip
        │   write <stem>.svg ─► rasterizer.rasterize ─► <stem>.png
        │        │ resvg absent → WARN+skip
        │   read_dimensions(png) ─► FigureEntry(origin_kind="generated")
        ▼
    merge(figure-catalog.json, generated)    merge_bindings(figure-bindings.json)
        └──────────────► write both (writer.write_json) ◄──────────────┘
                                   │
             assemble ─► build_bound_figures_resolver (unchanged)
               ├─ docx: BoundFigure.path = <stem>.png
               └─ html_render: swap .png→.svg when sibling exists (same dims)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `domain/ports/visual_renderer_port.py` | Create | `VisualRendererPort` Protocol (`type`, `render(spec)->str`); `VisualSpec` frozen dataclass. |
| `domain/ports/svg_rasterizer_port.py` | Create | `SvgRasterizerPort.rasterize(svg, png)`. |
| `domain/svg_normalize.py` | Create | Pure `normalize_svg(text)->str`. |
| `domain/figure_catalog.py` | Modify | Add pure `merge(existing, generated)`. |
| `domain/figure_binding.py` | Modify | Add pure `merge_bindings(existing, additions)`. |
| `domain/pipeline.py` | Modify | `_GENERATE_VISUALS` stage; insert into `assemble`/`all`. |
| `infrastructure/visuals/mermaid_svg_renderer.py` | Create | `mmdc --outputFormat svg`, subprocess+scratch, fail-open. |
| `infrastructure/visuals/chart_svg_renderer.py` | Create | matplotlib Agg SVG backend, declarative spec. |
| `infrastructure/visuals/resvg_rasterizer_adapter.py` | Create | resvg CLI, pinned font-dir, fail-open. |
| `infrastructure/docx/tool_resolver_adapter.py` | Modify | Add `resolve_resvg` / `resolve_mmdc`. |
| `application/generate_visuals.py` | Create | `GenerateVisualsService`: read specs, dispatch, merge, write, auto-bind. |
| `application/pipeline.py` | Modify | `stage_generate_visuals` callable; inject service. |
| `application/html_render.py` | Modify | Sibling `.png→.svg` swap after resolver, before strip. |
| `cli/_shared.py` | Modify | `visual_renderers` registry, guarded matplotlib construction, resvg adapter, service wiring. |
| `pyproject.toml` | Modify | `matplotlib` dep; resvg + `mmdc` documented external toolchain. |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class VisualSpec:
    label: str
    type: str          # "mermaid" | "chart"
    source: str        # inline text / JSON, OR a workspace-relative path
    caption: str = ""

class VisualRendererPort(Protocol):
    type: str
    def render(self, spec: VisualSpec) -> str: ...   # raw SVG text

class SvgRasterizerPort(Protocol):
    def rasterize(self, svg_path: Path, png_path: Path) -> None: ...
```

**normalize_svg** (exact operations, order-preserving, byte-stable):
1. strip XML comments `<!-- … -->` (tool-version/wall-clock).
2. strip `<metadata>…</metadata>` (matplotlib RDF `dc:date`; mermaid: none).
3. collect every `id="X"` in first-appearance order → map to `n0,n1,…`; rewrite
   each definition and reference (`#X`, `url(#X)`, `href="#X"`,
   `xlink:href="#X"`, `aria-labelledby`), replacing longest-id-first to avoid
   substring collisions. `# ponytail: regex over ids, not a full XML parse — upgrade to defusedxml if an id leaks past the anchored pattern.`

**Renderer-side determinism knobs** (set before generation, NOT in normalize):
- Mermaid: `mmdc --outputFormat svg`; the id-salt variance is handled entirely
  by `normalize_svg` step 3.
- Chart: `matplotlib.use("Agg")`; `rcParams["svg.hashsalt"]=<fixed>`;
  `rcParams["svg.fonttype"]="none"` (text as `<text>`, no font-path hinting);
  `savefig(format="svg", metadata={"Date": None})`; pinned `font.family`.

Cross-env identity is NOT guaranteed — it depends on pinned resvg + vendored
font + pinned mmdc/matplotlib versions (documented; same-machine same-inputs is
the contract, consistent with the existing Reproducibility Boundary Principle).

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (domain) | `normalize_svg` byte-stable across 2 runs of same renderer output; id-rewrite order-keyed | fixture SVGs (real mmdc + matplotlib captures), assert `sha256` equal |
| Unit (domain) | `merge` no-clobber + re-sorted; `merge_bindings` no-clobber | pure list/dict in→out |
| Unit (app) | registry dispatch by type; unknown type / bad spec → WARN+skip; missing resvg/mmdc → WARN+skip (no crash) | fake ports, capture stderr |
| Integration | each renderer produces normalizable SVG; resvg SVG→PNG + dims | real toolchain, `@skipif` absent |
| E2E | mermaid + chart spec → PNG in docx + SVG in HTML; byte-identical rebuild | full pipeline, assert artifact `sha256` stable |
| Regression | estadia characterization stays green | existing suite unchanged |

## Threat Matrix

Applicable boundary: subprocess invocation (mmdc, resvg) + execution of
agent-authored `visual-specs.json`.

| Boundary | Cases | Applicability | Design response | Planned RED tests |
|---|---|---|---|---|
| Documentation-like / execution boundary | spec `source` as inline text vs path; chart `source` containing code-like text | Applicable | `source` is DATA only — never `eval`/`exec`/`shell`; mermaid source written to a temp file, not a shell arg; chart source parsed as JSON | test: chart spec with Python-looking `source` renders as data, executes nothing; test: `source` path outside workspace is rejected |
| Subprocess arg composition | mmdc/resvg args | Applicable | fixed arg lists via `subprocess.run([...], check=True)` (no `shell=True`), input via temp file (`scratch_dir` precedent) | test: spec text with shell metacharacters never reaches a shell |
| Git repository selection | — | N/A | no VCS automation | — |
| Commit state | — | N/A | no VCS automation | — |
| Push state | — | N/A | no VCS automation | — |
| PR commands | — | N/A | no PR automation | — |

## Migration / Rollout

No migration. Additive and opt-in: absent `visual-specs.json` → generate-visuals
is a no-op; the pipeline behaves exactly as today. Revert = drop the stage
registration + adapters; `merge`/`origin_kind="generated"` are inert without
generated entries. `matplotlib` is the only hard new pip dep; resvg + mmdc are
optional PATH toolchain (doctor `Check(required=False)` guidance).

## Delivery Forecast (for sdd-tasks)

Big feature; slice into ≤~400-line PRs (5–7 slices):
1. Ports + `VisualSpec` + `normalize_svg` (domain, pure) + `merge`/`merge_bindings`.
2. `ChartSvgRenderer` (matplotlib) + guarded composition — no external toolchain.
3. `MermaidSvgRenderer` (mmdc) + `resolve_mmdc`.
4. `SvgRasterizerPort` + resvg adapter + `resolve_resvg` + dims.
5. `GenerateVisualsService` + stage wiring + ordering + auto-bind.
6. `html_render` sibling-SVG swap + E2E byte-identity.
7. doctor capability checks + docs/pyproject.

`400-line budget risk: High` (multi-file feature) → chained PRs recommended.

## Open Questions

- [ ] Vendored font choice for cross-env parity (design accepts same-machine
      contract; pin a single font for both matplotlib `font.family` and resvg
      `--use-fonts-dir`).
- [ ] `mmdc` (official) reintroduces headless-Chrome cost — accepted per proposal
      Decision 2 as an optional fail-open toolchain; revisit if a Chrome-free
      mermaid renderer (mermaidx/mmdr) proves stable.
