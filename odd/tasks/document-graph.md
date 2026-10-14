# Document graph

## Objective
Turn the half-built semantic graph into a real feature: a deterministic,
no-LLM graph of each document's traceability (sources, evidence, claims,
sections, requirements, references, revisions, findings, artifacts), computed
from data the harness already persists, answering review questions in Review
Studio and the API.

## Why
Review Studio ships a Graph tab whose five queries always answer "graph read
model is unavailable": nothing produces a `SemanticGraph` (projector removed
in 8b378422 as unwired), and the runtime `Graph` store is never written.
Traceability is the core promise of a document harness; the data already
exists on disk (mapping 2026-10-14), only the projection and a few links are
missing.

## Users and value
- Reviewer: "which claims are unconfirmed", "which requirements are unmet",
  "which references are never cited", "what did revision N break",
  "which outputs are stale because a source changed".
- Author: same answers before publishing, via CLI.
- Developer: one graph model, one spec, one projector to extend.

## Data sources (evidence: mapping report 2026-10-14)
- sections: `documents/<doc>/sections/NNN-<id>.md` frontmatter.
- requirements: template `SectionContract.required_content`, required
  sections/topics; satisfaction via `rules.requirement_present`.
- references/citations: `domain/apa.py` extract functions.
- claims: fact ledger `source-manifest.json facts[]` (classification).
- evidence/inputs: `sections/source-manifest.json sources[]`,
  `inbox/_source-manifest.json`, figure catalog.
- artifacts/derived_from: provenance ledger `runs/provenance.json`.
- revisions: `sections/_revisions/revision-log.json entries[]`.
- findings per revision: NOT persisted today (task G2).

## Constraints
- Strict TDD (CLAUDE.md; `uv run pytest`; review-studio uses its own test
  runner). Deterministic output: same files -> identical graph.
- Hexagonal: projector is pure domain; file reading is an infrastructure
  adapter wired only in the composition root.
- Projection on read with mtime-keyed cache; no new persistent store.
- Every query distinguishes "no data" from "nothing wrong".
- Delivery: stacked PRs per slice, native review per slice, CI green, merge
  to main (user-authorized).

## Tasks
- [x] G1 Fix `/v2/revisions`: `sidecar/stores.py` reads `items` but the log
      key is `entries`.
- [x] G2 Persist review `Issue.to_dict()` lists in each revision-log entry
      (`application/revision.py`), so revisions link to the findings they
      produced.
- [x] G3 Stable fact ids (hash of classification|claim|source) and a
      structured `source_path` on ledger facts when the source is a file.
- [x] G4 Pure domain projector `domain/document_graph.py`: snapshot of the
      above -> `SemanticGraph` (kinds: document, section, source, evidence,
      claim, requirement, reference, revision, finding, artifact, input;
      relations: contains, supports, satisfies, references, cites, affects,
      derived_from, revises). Deterministic ordering and ids.
- [x] G5 Infrastructure adapter: reads one workspace's documents into the
      snapshot, mtime cache, implements `SemanticGraphStore.for_workspace`;
      wire in composition root and sidecar `semantic_graph_store`.
- [x] G6 New queries with real value: `stale_artifacts` (ledger input hashes
      vs current files), `source_impact` (artifacts/sections reached from a
      source), `requirement_coverage` (per section: satisfied/missing).
      API + OpenAPI.
- [x] G7 One graph model: raw `GET /v2/graph` serves the semantic graph;
      remove the never-written runtime `Graph` store/route path.
- [x] G8 Review Studio GraphPanel: new queries, explicit empty vs
      no-data states, per-document filter.
- [x] G9 CLI `docs graph <query>` (Spanish UI strings) for authors.
- [x] G10 Capability spec `openspec/specs/document-graph/spec.md` (+ pinned
      count), end-to-end test (ingest -> build -> revise -> graph query via
      API), AGENTS.md entry.

## Acceptance
- All 5 original queries plus G6 return real data on a workspace that ran the
  normal pipeline; each reports "no data" honestly when its source is absent.
- Full suite, ruff, mypy, review-studio tests, CI green; architecture tests
  green.

## Progress
- Branch: `feat/document-graph` (from main f4a8803c).
- G1 done: RED `KeyError: 'section_id'` (store returned whole log as one record), GREEN after reading `entries`; test_sidecar.py 30 passed, ruff, mypy clean.
- G2 done: RED 2 failed (no `issues`/`id` in entry), GREEN after persisting `Issue.to_dict()` lists (section + document, topic ripple too) and `id = sha256_content(entry)`; old logs load unchanged (entries are only appended). test_revision + test_section_routes 38 passed, ruff, mypy clean.
- G3 done: RED ImportError `identify_facts`; GREEN with `domain/collection.py:identify_facts` (id = sha256 of the dedupe key, first 16 hex; `source_path` when the source is a collected file; dependency facts carry their manifest path). Ledger render reads only classification/claim, so its output is unchanged (`-k ledger` green). Collection tests green, ruff, mypy clean. `ledger_seed` is template config, never persisted, so it is untouched.
- G4 done: RED collection ImportError (no module), GREEN 8 tests in tests/unit/domain/test_document_graph.py (namespacing, supports via source_path, satisfies via requirement_present, references via apa author keys, revision->finding/section, derived_from, determinism under reordering, legacy revisions). `GraphQueryService` constants/relations already matched (no change); all 5 queries verified on a projected graph. Relation `cites` was folded into `references` (queries only know `references`). ruff, mypy clean. Module: src/docs/domain/document_graph.py (~190 lines).
- G5 done: RED `graph unavailable: no semantic graph store configured` from the API; GREEN with `infrastructure/graph/document_graph_reader.py` (`DocumentGraphReader`, cache keyed by (path, mtime_ns) of every file read), `composition.open_document_graph_reader`, `sidecar/stores.py:WorkspaceSemanticGraphStore` wired as `semantic_graph_store` in `sidecar/app.py`. New read-only port `SemanticGraphReader` (consumers use it; `SemanticGraphStore` extends it). tests/integration/test_document_graph_api.py: 3 passed (API answers artifacts_derived_from_input, unmet_requirements, unused_references, claims_without_evidence, findings_affected_by_revision with real ids; cache invalidation; empty workspace). ruff, mypy clean; architecture + unit/api + test_sidecar green (see commit).
- G6 done: RED 10 failed (no `current_sha256`, no `stale_artifacts`/`source_impact`/`requirement_coverage`/`coverage`) + 6 API tests failed; GREEN after: `FileEntry.current_sha256` measured by the reader (`DocumentGraphReader._digest`, cached by path+mtime+size) and compared by the projector (artifact attrs `stale`/`stale_inputs`; an artifact is fresh if ANY run that built it matches today's files); ledger/manifest paths normalised to document-relative keys with `domain/paths.is_within` (paths outside the workspace keep their raw form and are never opened); build inputs link to their section (`contains`), source/evidence (`supports`); template `ledger_seed` facts become claims (source `template`); `GraphQueryService.stale_artifacts/source_impact/requirement_coverage/coverage`; every `/v2/graph` query payload now carries `no_data` + `coverage` (node counts of the kinds it stands on), absent only with `graph_unavailable`; OpenAPI enum built from `graph_routes.GRAPH_QUERIES` + `source_id` param. Integration fixture now stores absolute ledger paths like the real ledger. 622 passed (domain graph, application, integration graph API, test_sidecar, tests/architecture), tests/unit/api 451 passed, ruff, mypy clean. Reader tests for normalisation/seed were written after the reader change (no separate RED observed for those three).
- G7 done: RED 9 failed (`ApiApplication()` still demanded `graph_store`; raw route served the runtime Graph) -> GREEN: `GET /v2/graph` and `/v2/runs/{id}/graph` serve the projected `SemanticGraph` (`nodes`/`edges` as objects, plus `no_data`; `graph_unavailable`+`warnings` when no store is configured/readable); `GraphQueryService.graph()`; removed the host `graph_store` slot, `WorkspaceGraphStore`/`View`, `RuntimeStores.graph`, and (flagged by `test_ports_have_consumers`) the orphaned `GraphStore` port, `runtime_records.Graph`, `SqliteGraphStore` and the in-memory fake with their tests. The old `runtime_graph` table is left in existing DBs untouched (`# ponytail:` note in `sqlite_runtime.py`). OpenAPI: `graph` schema now references `graph_node`/`graph_edge` (+ `no_data`, `graph_unavailable`, `warnings`). tests/unit/api 455 passed, sidecar/runtime stores/integration 44 passed, tests/architecture 131 passed, ruff, mypy clean.
- G8 done: RED vitest 8 failed (client no_data/coverage/sections + unavailable overview, raw revision rows, 3 new queries, states, document filter) + pytest 1 failed (revision records had no `document_id`/id for legacy entries) -> GREEN. Server: `/v2/revisions` rows now carry `document_id` and, for legacy entries, the same content-hash `id` the graph uses. Studio: `toRevision` maps raw revision-log entries to timeline rows (the old UI read `message/author/date/status/files`, which the one-record-per-entry shape never had; author = document, status from issue severities); `GraphPanel` has the 8 queries, a Document filter (client-side by node-id prefix), id completions from the overview nodes, and distinct states: unavailable (alert) / no data (`No data to check`, with counts) / nothing found (`Nothing found ... Checked N kind`) plus a per-section requirement table; overview distinguishes unavailable from empty. UI strings stay English like the rest of the app. review-studio: vitest 246 passed, `tsc --noEmit` and eslint clean; test_sidecar 31 passed; ruff, mypy clean.
- G9 done: RED 10 failed (no `graph` command, no `GraphQueryService.answer`) -> GREEN: `docs graph <query> [--id] [--json]` (`cli/commands/graph_app.py`, Spanish help/messages; `--doc` filters to one document; exit 2 on unknown query/missing `--id`, 1 when the graph is unavailable; "Sin datos" vs "Nada encontrado" are distinct lines). Shared `GraphQueryService.answer()`/`GraphAnswer`/`NAMED_QUERIES` now back both the CLI and the API route (route refactored onto it, OpenAPI enum derives from `NAMED_QUERIES`). Wired as `ApplicationComposition.graph_queries` over `open_document_graph_reader`. Parity: capability `graph` -> `GET /v2/graph` (slice S4), `parity-ui.json` row, matrix regenerated (`tools/regen_parity_matrix.py`). AGENTS.md section "Traceability queries: docs graph". tests/architecture + tests/unit/api + agents-md 599 passed; CLI/application targeted 55 passed; ruff, mypy clean.
- G10 done: `openspec/specs/document-graph/spec.md` (9 requirements with scenarios; names `project_document_graph`, `DocumentGraphReader`, `GraphQueryService`, `GraphRoutes`, `SemanticGraph`, `DocumentSnapshot`, ...), pinned capability count 13 -> 14 in `test_spec_symbol_references.py` and CLAUDE.md; `tests/integration/test_document_graph_e2e.py`: real `source ingest` + `collect-sources` + `doc revise` through the CLI runner, the build's provenance run recorded with `ProvenanceLedger` and the pipeline's own `_build_inputs` (a full DOCX build fails the editorial review on a toy document, so it is not run), then all 8 queries over the sidecar API with no_data false and `coverage` present (also cross-checks `/v2/revisions` ids against the graph's revision node ids); guard that the e2e covers every `NAMED_QUERIES` entry. AGENTS.md "Where do I add X" entry. Passed: architecture + unit/api + agents-md + graph integration 617; unit application/domain/infrastructure/sidecar/runtime-stores 1759; ruff, mypy clean. Full Python suite not run (CI).
- Branch complete (G1-G10). Open follow-ups: the Studio `Graph` tab still shows only queries (no node-link visualisation); `stale_artifacts` needs a build to have run (otherwise no data, by design); API has no server-side `document` filter (CLI/Studio filter by id prefix).
