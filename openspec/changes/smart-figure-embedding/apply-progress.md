# Apply Progress: Smart Figure Embedding

Artifact store: hybrid (this file + Engram `sdd/smart-figure-embedding/apply-progress`).

## S1 — Domain: filter + fields — DONE

- [x] 1.1 RED `tests/unit/domain/test_figure_filter.py` (new, 7 cases per ADR-2/ADR-7)
- [x] 1.2 GREEN `src/docs/domain/figure_filter.py` (new) — `MIN_FIGURE_DIMENSION_PX=100` + `should_catalog_figure`
- [x] 1.3 RED extended `tests/unit/domain/test_figure_catalog.py` (+3 cases: defaults, round-trip, byte-identical w/ new fields)
- [x] 1.4 GREEN `src/docs/domain/figure_catalog.py` — added `source_role: str = ""`, `origin_kind: str = ""` to `FigureEntry`; `build()` emits both, additive only (existing keys unchanged/unreordered)
- [x] 1.5 Slice check green: `tests/unit/domain/test_figure_filter.py` + `tests/unit/domain/test_figure_catalog.py` = 15 passed. Full suite: 1342 passed, 0 failed, 7 skipped. `ruff check` clean on all 4 changed/new files.

Commits (branch `feat/usfe-s1-domain-filter`, off main `16294dc`):
- `cbe0516` feat(domain): add pure should_catalog_figure role/size filter
- `e327048` feat(domain): add source_role/origin_kind to FigureEntry

Touched only S1 files: `src/docs/domain/figure_filter.py` (new),
`src/docs/domain/figure_catalog.py` (modified),
`tests/unit/domain/test_figure_filter.py` (new),
`tests/unit/domain/test_figure_catalog.py` (modified). No S2/S3/S4 files
touched (`application/ingest.py`, `domain/figure_binding.py`,
`domain/cross_reference.py`, `application/section_markdown.py`,
`application/docx_assembly.py`, `application/html_render.py` all
untouched).

## Next

S2 — ingest wiring (tasks 2.1–2.9) — not started. Depends on S1's
`FigureEntry` fields + `figure_filter` (both now available).
