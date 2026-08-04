# Apply Progress: On-Demand Visual Generation

Artifact store: hybrid (this file + Engram `sdd/on-demand-visual-generation/apply-progress`).

## Slice 1 — Domain foundation: ports, VisualSpec, normalize_svg, merge/merge_bindings — DONE

- [x] 1.1 RED `tests/unit/domain/test_visual_renderer_port.py` (new, 5 cases) +
  `tests/unit/domain/test_svg_rasterizer_port.py` (new, 2 cases).
  GREEN `src/docs/domain/ports/visual_renderer_port.py` (new: `VisualSpec`
  frozen dataclass, `VisualRendererPort` Protocol) +
  `src/docs/domain/ports/svg_rasterizer_port.py` (new: `SvgRasterizerPort`
  Protocol).
- [x] 1.2 RED `tests/unit/domain/test_svg_normalize.py` (new, 7 cases,
  including the critical byte-stability proof: two structurally-identical
  SVGs differing only in ids/comments/metadata dates -> identical sha256).
  GREEN `src/docs/domain/svg_normalize.py` (new): strips XML comments, strips
  `<metadata>`, collects `id="X"` in first-appearance order, rewrites every
  definition/reference form (`#X`, `url(#X)`, `href="X"`/`href="#X"`,
  `xlink:href="#X"`, `aria-labelledby="X"`) to `n0,n1,...`, replacing
  longest-id-first (proven via a CSS-selector `#abc`/`#a` collision test).
- [x] 1.3 RED extended `tests/unit/domain/test_figure_catalog.py` (+3 cases:
  no-clobber, resorted+deterministic, safe-to-rerun). GREEN
  `src/docs/domain/figure_catalog.py` — added `merge(existing_catalog: dict,
  generated: dict) -> dict`, union by `id`, existing wins on collision,
  re-sorted by `id` (same shape/determinism as `build()`).
- [x] 1.4 RED extended `tests/unit/domain/test_figure_binding.py` (+3 cases:
  adds-only-absent, never-clobbers, sorted+deterministic). GREEN
  `src/docs/domain/figure_binding.py` — added `merge_bindings(existing: dict,
  additions: dict) -> dict`, adds `label -> id` only when label absent,
  sorted-key output.
- [x] 1.5 Slice check green: 33 new/extended domain tests passed. Full suite:
  1396 passed, 0 failed, 7 skipped (zero regression). `ruff check` clean on
  all 9 changed/new files.

Commits (branch `feat/odvg-s1-domain`, off main `e43efec`):
- `9b4efba` feat(domain): add VisualRendererPort, VisualSpec, SvgRasterizerPort
- `117f657` feat(domain): add normalize_svg determinism pass for generated SVGs
- `7a8927e` feat(domain): add no-clobber merge() to figure_catalog
- `08b232a` feat(domain): add no-clobber merge_bindings() to figure_binding

Touched only Slice-1 (pure domain) files:
`src/docs/domain/ports/visual_renderer_port.py` (new),
`src/docs/domain/ports/svg_rasterizer_port.py` (new),
`src/docs/domain/svg_normalize.py` (new),
`src/docs/domain/figure_catalog.py` (modified, additive),
`src/docs/domain/figure_binding.py` (modified, additive),
`tests/unit/domain/test_visual_renderer_port.py` (new),
`tests/unit/domain/test_svg_rasterizer_port.py` (new),
`tests/unit/domain/test_svg_normalize.py` (new),
`tests/unit/domain/test_figure_catalog.py` (modified, extended),
`tests/unit/domain/test_figure_binding.py` (modified, extended).
No `application/`, `infrastructure/`, or `cli/` files touched (Slices 2-7
untouched — they depend on this slice's domain contracts).

Not started: Slices 2-7 (`ChartSvgRenderer`, `MermaidSvgRenderer`,
`SvgRasterizerPort` resvg adapter, `GenerateVisualsService` + stage wiring,
`html_render` sibling-SVG swap + E2E, doctor checks + pyproject + AGENTS.md).
