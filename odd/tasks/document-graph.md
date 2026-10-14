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
- [ ] G5 Infrastructure adapter: reads one workspace's documents into the
      snapshot, mtime cache, implements `SemanticGraphStore.for_workspace`;
      wire in composition root and sidecar `semantic_graph_store`.
- [ ] G6 New queries with real value: `stale_artifacts` (ledger input hashes
      vs current files), `source_impact` (artifacts/sections reached from a
      source), `requirement_coverage` (per section: satisfied/missing).
      API + OpenAPI.
- [ ] G7 One graph model: raw `GET /v2/graph` serves the semantic graph;
      remove the never-written runtime `Graph` store/route path.
- [ ] G8 Review Studio GraphPanel: new queries, explicit empty vs
      no-data states, per-document filter.
- [ ] G9 CLI `docs graph <query>` (Spanish UI strings) for authors.
- [ ] G10 Capability spec `openspec/specs/document-graph/spec.md` (+ pinned
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
- Next: G5.
