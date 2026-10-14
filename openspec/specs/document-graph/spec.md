# Document Graph Specification

## Purpose

Answer traceability questions about a document ("which claims have no evidence", "which requirements are unmet", "which outputs are stale because a source changed") from a deterministic graph that is projected from files the harness already persists, with no LLM and no second store.

Implemented by `project_document_graph` (pure projection of `DocumentSnapshot` values into a `SemanticGraph`), `DocumentGraphReader` (reads one workspace's files into those snapshots and caches the projection), and `GraphQueryService` (the named queries and their no-data signal). The CLI entry point is the `graph_app` module's `docs graph` command and the HTTP entry point is `GraphRoutes` serving `GET /v2/graph`.

The graph is a read model. Nothing writes it, and the projector never reads a file.

## Requirements

### Requirement: Deterministic Projection

The system MUST project the same files into a byte-identical graph. Node ids MUST be `<document>/<kind>/<key>` with a key derived from content or path, never from the clock or from iteration order, so that documents in one workspace never collide.

#### Scenario: Reordered input yields the same graph

- GIVEN two snapshots of one document whose sections and facts are listed in different orders
- WHEN each is projected
- THEN both graphs have the same `graph_id`

#### Scenario: Two documents do not collide

- GIVEN two documents with identically named sections
- WHEN both are projected into one graph
- THEN every node id is unique and begins with its own document id

### Requirement: Cached Projection From Files

The system MUST build the graph from files already on disk and MUST invalidate its cache from the path and modification time of every file it read, so a deleted or renamed file also invalidates it. A workspace without documents MUST project to an empty graph, not fail.

#### Scenario: A watched file changes

- GIVEN a graph that was read once
- WHEN a section file is edited and the graph is read again
- THEN the projection is rebuilt and reflects the edit

#### Scenario: Nothing changed

- GIVEN a graph that was read once
- WHEN it is read again with no file changed
- THEN the same projected object is returned

### Requirement: Stable Identity For Files

The system MUST give a file one node key whatever form recorded it. Provenance-ledger paths (absolute, or relative to `runs/`) and manifest paths MUST be normalised relative to the document, using the path-confinement rule. A path that resolves outside the workspace MUST keep its raw form and MUST NOT be opened.

#### Scenario: A ledger input is an absolute path inside the document

- GIVEN a ledger run whose input is the absolute path of a section file
- WHEN the graph is read
- THEN the input node id ends with `sections/<file>` relative to the document

#### Scenario: A ledger input points outside the workspace

- GIVEN a ledger input outside the workspace root
- WHEN the graph is read
- THEN the input keeps its raw path
- AND the reader does not hash or open it

### Requirement: Stale Artifacts

The system MUST flag an artifact as stale when a build input's current hash differs from the hash the ledger recorded, or the file is gone. Hashing current files MUST be done by the reader; the projector MUST only compare. An artifact rebuilt by a later run MUST be fresh when any run that produced it matches today's files. An artifact whose inputs were never compared MUST carry no verdict.

#### Scenario: A source file is edited after the build

- GIVEN an artifact recorded by a run whose input hashes matched at build time
- WHEN an input file is edited
- THEN `GraphQueryService.stale_artifacts` returns that artifact

#### Scenario: Nothing was compared

- GIVEN a graph whose artifacts have no measured current hashes
- WHEN `stale_artifacts` is asked
- THEN the answer is reported as no data, not as an empty list of stale artifacts

### Requirement: Source Impact And Requirement Coverage

`source_impact` MUST return the artifacts and sections reachable from a source, evidence or input node, and MUST NOT traverse `contains` edges out of a document node. `requirement_coverage` MUST return, per section, the requirements its text satisfies and those it is missing.

#### Scenario: A source reaches an artifact through its input file

- GIVEN a source file that is also a build input of an artifact
- WHEN `source_impact` is asked for the source
- THEN the artifact is returned

#### Scenario: A section misses one requirement

- GIVEN a section whose template requires three topics and whose text covers two
- WHEN `requirement_coverage` is asked
- THEN that section lists two satisfied and one missing requirement

### Requirement: Claims From The Fact Ledger

Facts collected into the manifests and the template's `ledger_seed` facts MUST project as claims, each with a stable content-derived id. A claim MUST be linked to evidence only through the structured `source_path` of its fact, never by matching free text.

#### Scenario: A template seeds a fact

- GIVEN a template whose `ledger_seed` holds a claim
- WHEN the graph is read
- THEN that claim is a node with the seed's classification

### Requirement: No Data Is Not Nothing Wrong

Every query answer MUST say whether the data it stands on exists. A named query MUST return `no_data` and a `coverage` mapping of node counts per kind, and a query whose subject kinds have zero nodes MUST report `no_data` true. An unreadable graph MUST be reported as `graph_unavailable`, a third and distinct state.

#### Scenario: Empty answer over real data

- GIVEN a graph with claims that all have evidence
- WHEN `claims_without_evidence` is asked
- THEN `items` is empty and `no_data` is false and `coverage` counts the claims it checked

#### Scenario: Empty answer over no data

- GIVEN a graph with no claims
- WHEN `claims_without_evidence` is asked
- THEN `items` is empty and `no_data` is true

### Requirement: One Graph Model On The API

`GET /v2/graph` and `GET /v2/runs/{run_id}/graph` MUST serve the projected `SemanticGraph` as node and edge objects. The named queries MUST be selectable as `query=<name>&id=<node>` or `mode=<name>` with a per-query id parameter, and a query that needs an id MUST answer 400 without one.

#### Scenario: Raw graph

- GIVEN a workspace with documents
- WHEN `GET /v2/graph` is requested
- THEN `nodes` and `edges` are objects with `kind`, `label` and `confidence`

#### Scenario: Missing subject id

- WHEN `GET /v2/graph?query=source_impact` is requested without `id`
- THEN the response is 400 with code `invalid_graph_query`

### Requirement: Author Command

`docs graph <query>` MUST answer the same named queries from the same reader, print the API payload with `--json`, restrict to one document with `--doc`, and say "Sin datos" for no data and "Nada encontrado" for an empty answer over real data. An unknown query or a missing `--id` MUST exit with code 2.

#### Scenario: No data

- GIVEN a workspace with no claims
- WHEN `docs graph claims_without_evidence` runs
- THEN the output says "Sin datos" and exits 0

#### Scenario: Unknown query

- WHEN `docs graph nope` runs
- THEN the command exits with code 2
