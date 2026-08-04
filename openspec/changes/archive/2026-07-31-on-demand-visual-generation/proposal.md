# Proposal: On-Demand Visual Generation

## Intent

Today an author can only embed figures that already exist as raster files dropped in `inbox/`. Diagrams and data charts must be produced by hand in an external tool, exported, and dropped in — friction that keeps living documents out of date. This change lets the agent DECLARE a visual (Mermaid diagram or data chart) as intent and have the harness generate, catalog, bind, and embed it deterministically — extending Sub-project 1's figure foundation, not replacing it. It ships an EXTENSIBLE renderer framework (a `VisualRendererPort` registry) with two first renderers; PlantUML/graphviz later = implement the port + register.

## Scope

### In Scope
- `VisualRendererPort` (domain/ports) + registry in the composition root, keyed by visual `type` (mirrors `ingest_handlers` by `kind`).
- Two adapters: Mermaid (official `mmdc`, SVG out) and Chart (matplotlib SVG backend).
- Deterministic pipeline per visual: renderer→SVG→normalize→**SVG kept for HTML** + **rasterized PNG for docx** (resvg).
- New `generate-visuals` pipeline stage (after ingest, before assemble).
- Agent artifact `sections/visual-specs.json` (`{label,type,source,caption}`) + auto-bind into `figure-bindings.json`.
- Deterministic catalog MERGE (generated entries never clobber ingest entries).
- Graceful degradation: missing toolchain / malformed spec → WARN+skip that visual, never crash the stage or build.

### Out of Scope
- Fixing standalone-`.svg` INGEST (Decision 6 — deferred; different code path, needs an SVG dim-reader + ingest-time rasterization).
- PlantUML/graphviz/other renderers (framework supports them; not built now).
- Interactive/animated or themeable visuals; SVG-in-docx (impossible, pandoc#9195).

## Capabilities

### New Capabilities
- `document-visuals`: declare→generate→normalize→rasterize→catalog-merge→auto-bind for agent-authored visuals; the `VisualRendererPort` contract and fail-open rules.

### Modified Capabilities
- `asset-management`: `origin_kind="generated"` entries; catalog MERGE contract; `origin_relative_path`→PNG with sibling-`.svg` convention.
- `document-pipeline`: `generate-visuals` stage + ordering guarantee (after ingest, before assemble).
- `document-render`: HTML prefers sibling `.svg`; docx uses the PNG.
- `agent-contract`: `visual-specs.json` as a new agent-authored artifact + schema.

## Approach — Key Architectural Decisions (pre-resolved)

| # | Decision | Resolution |
|---|----------|-----------|
| 1 | Catalog model for 2-artifact visual | **ONE entry, `origin_relative_path`→the PNG.** Docx + the shared resolver's non-null-dims guard are satisfied by the PNG's raster dims — zero change to catalog/resolver/domain. HTML swaps `.png`→sibling `.svg` locally in `html_render` (same stem in `assets_dir/figures/`, same `width_px`). Smallest change to Sub-project 1. TWO entries or a format-aware resolver both touch the shared signature/binding UX. |
| 2 | Rasterizer | **resvg CLI, PATH-resolved + fail-open** via `ToolResolverPort` — Chrome-free, deterministic, font-dir pinnable. Avoids cairosvg's Cairo/fontconfig cross-env non-determinism. NEW toolchain dep; pin version + vendor a font in install guidance. |
| 3 | SVG dimensions | **From the renderer at generation time** (matplotlib inches×dpi; mermaid `<svg>` viewBox via defusedxml). No post-hoc reader; `ImageMetadataPort` untouched. PNG px are set by the rasterize step (confirmable via pillow). |
| 4 | Catalog merge | **Pure `merge()` helper in `domain/figure_catalog.py`**: union by id, re-sort by id, deterministic; I/O in the stage. Ingest overwrites then generate merges → re-run generate-visuals after any ingest. |
| 5 | Visual-spec + binding UX | `sections/visual-specs.json` confirmed. **Auto-bind**: the agent cannot know the content-hash `fig-<sha8>` id, so agent-must-bind is infeasible for generated visuals; the harness owns the id and merges label→id into `figure-bindings.json` (no clobber). Agent = intent, harness = mechanics. |
| 6 | Standalone-SVG ingest gap | **Deferred** (see Out of Scope) — not shared with the generated path, not a cheap drive-by. |
| 7 | Stage ordering | prep → ingest → build-sections (agent authors sections + visual-specs.json) → **generate-visuals** → assemble. Markers are plain text resolved at assemble, so no build-sections dependency. |

Hexagonal boundaries preserved: port in `domain/ports`, adapters in `infrastructure`, stage + registry in `application`/composition root.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `domain/ports/visual_renderer_port.py` | New | `VisualRendererPort` protocol. |
| `domain/figure_catalog.py` | Modified | Pure `merge()` helper; `origin_kind="generated"`. |
| `infrastructure/visuals/` | New | Mermaid + Chart adapters; resvg rasterize + SVG normalize. |
| `application/generate_visuals.py` | New | `generate-visuals` stage (read-merge-write catalog + bindings). |
| `application/html_render.py` | Modified | Sibling-`.svg` preference before markdown substitution. |
| `domain/pipeline.py` / `application/pipeline.py` | Modified | Register stage + ordering. |
| `cli/_shared.py` | Modified | `visual_renderers` registry, guarded optional-toolchain construction. |
| `pyproject.toml` | Modified | matplotlib dep; resvg + mmdc documented as external toolchain. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| matplotlib SVG non-determinism (font hinting, random ids) | Med | Normalize (`svg.hashsalt`, pinned font, id rewrite) + byte-identity spike in design. |
| Mermaid SVG random element ids | Med | Order-keyed id rewrite before hashing into `sha256`. |
| resvg/mmdc absent on a machine | Med | Fail-open WARN+skip per visual (mirrors PDF renderer); build never crashes. |
| Cross-env byte drift from external tools | Med | Pin versions + vendor font; determinism contract is same-env same-inputs. |
| Ingest re-run drops generated entries | Low | Documented ordering; generate-visuals re-runs after ingest. |

## Rollback Plan

The stage is additive and opt-in: absent `visual-specs.json` → generate-visuals is a no-op and the pipeline behaves exactly as today. Revert = remove the stage registration + adapters; the catalog `merge()` helper and `origin_kind="generated"` are inert without generated entries. No migration of existing artifacts.

## Dependencies

- matplotlib (new pip dep, SVG backend).
- resvg CLI and mermaid-cli (`mmdc`) — external toolchain, PATH-resolved, optional/fail-open.

## Success Criteria

- [ ] A `visual-specs.json` Mermaid entry produces a crisp SVG in HTML and an embedded PNG in docx, both bound and numbered via the existing figure pipeline.
- [ ] A chart entry does the same without any Node/Chrome toolchain present.
- [ ] Re-running the build yields byte-identical outputs (determinism test).
- [ ] Missing resvg/mmdc or a malformed spec entry → WARN+skip that visual; the rest of the build succeeds.
- [ ] generate-visuals merges into figure-catalog.json without dropping ingest entries.
- [ ] Adding a third renderer requires only a new adapter + registry entry (no stage/resolver change).
