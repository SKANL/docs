# Architecture consolidation

## Objective
Make the codebase stable and easy to extend before new features land: one
composition root, no ceremonial ports, no duplicated cross-cutting logic,
domain logic out of giant adapters.

## Problem (evidence from mapping, 2026-10-13)
- cli/sidecar/workers instantiate `Sqlite*Store` and other infrastructure
  directly instead of going through `ApplicationComposition`
  (`cli/commands/document_run.py:63,83,127,138,152`, `sidecar/stores.py:182-392`,
  `workers/composition.py:222`).
- Registry/state-path resolution duplicated ~6 times; `runtime.sqlite3` path
  rebuilt inline 6 times in `sidecar/stores.py`.
- Confine-then-remap-error duplicated 4 times; fail-open JSON read duplicated
  (`generate_visuals.py:84`, `figure_resolver.py:15`, sidecar, composition).
- 7 ports with one impl and zero fakes; 3 ports split over one class
  (`JsonDocumentRepository`); `PlatformSandboxProvider` has no prod impl.
- `composition.py` (747 lines) mixes config/token logic with wiring and types
  several attributes as `Any` or concrete adapters.
- Giant adapters hold pure theme/geometry logic.

## Constraints
- Strict TDD (source: CLAUDE.md; runner `uv run pytest`). RED before GREEN.
- Behaviour-preserving: no CLI/API contract change.
- Determinism invariants and architecture tests stay green.
- Checks per task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
- ~400 authored lines per task is advisory only.
- Delivery strategy: ask-on-risk (default).

## Tasks
- [x] T1 Architecture test: only `composition.py` (and `infrastructure/`)
      may import `docs.infrastructure`; start with an explicit allowlist of
      current violators that later tasks shrink to empty. Route: inline.
- [x] T2 `RuntimeStores` bundle + single `state_path`/registry resolution,
      exposed by the composition root; migrate cli (`run_app`, `document_run`)
      to it. Route: delegated writer.
- [x] T3 Migrate sidecar (`stores.py`, `app.py`, `worker.py`) to the bundle;
      delete inline `runtime.sqlite3` paths. Route: delegated writer.
- [x] T4 Collapse `workers/composition.py` production factories into the root
      (drop dead `create_production_worker*`). Route: delegated writer.
- [x] T5 Move locking/guard helpers behind the composition root for cli
      (`document_release`, `document_batch`, `document_app`); empty the T1
      allowlist. Route: delegated writer.
- [x] T5b Provenance port: inject the ledger through the composition root so
      `application/provenance.py` drops its infrastructure import; delete
      `KNOWN_EXCEPTIONS`. Route: delegated. (Added after T5 deviation.)
- [x] T6 Shared helpers: one confine→error mapper, one fail-open JSON reader
      in domain/identity-adjacent module; replace duplicates. Route: delegated.
- [x] T7 Port pruning: inline the 7 one-impl/zero-fake ports after confirming
      no test substitutes them; merge Document/Registry/Template repository
      ports; drop or justify `PlatformSandboxProvider`. Route: delegated.
- [x] T8 Split `composition.py`: config/token/path logic out to
      `application/workspace_config.py`; type attributes as ports. Route:
      delegated.
- [x] T9 Extract `VisualTheme` + helpers to `domain/theme.py`, pure OOXML zip
      helpers to their own module. Route: delegated.
- [x] T10 Extract PDF layout/geometry helpers to `domain/pdf_layout.py`.
      Route: delegated.
- [x] T11 Contributor map: short "where do I add X" section in AGENTS.md.
      Route: inline.
- [x] T12 Resolve the shrink-only allowlist in `test_ports_have_consumers.py`
      (`blob_store`, `graph_store`, `plugin_executor`); delete the allowlist.
- [ ] T13 Prove `tests/unit/domain/test_pdf_layout.py` is not vacuous by
      mutating each tested function and observing RED.

## Acceptance
- No module outside `composition.py`/`infrastructure/` imports infrastructure
  (mechanised by T1).
- Full suite, ruff, mypy, coverage floor green after every task.

## Progress
- Branch: `refactor/single-composition-root`.
- T1 done (commit 6a2be37b). RED: with empty ALLOWLIST the scan reported 12
  violators (the mapped 10 plus `local_worker.py` and the dynamic
  `import_module` in `application/provenance.py`); GREEN with the allowlist.
  Full suite 3206 passed, 3 failed (2 in `tests/unit/plugins/test_sdk.py`
  process-timeout tests, flaky under full-suite load: 32/32 pass in
  isolation), ruff and mypy clean. Full suite takes ~21 min.
- T2 done (commit 70ea2b16). RED: `tests/unit/test_runtime_stores.py` failed at collection
  (ImportError on `RuntimeStores`, `resolve_workspace_registry`,
  `resolve_runtime_root`, `runtime_state_path`); GREEN 5 passed. Added to
  `composition.py` (lazy `RuntimeStores`, one registry/state-path
  resolution); `cli/commands/run_app.py` and `document_run.py` migrated and
  removed from the allowlist (`document_app.py` adapted to the new
  `durable_evidence_stores` return). Targeted: architecture + unit/cli +
  composition 151 passed; ruff and mypy clean. Full suite runs in a side
  worktree (~21 min) and is reported in the final handoff.
- T3 done (commit b688e2cd). RED: sidecar test with the new `build_worker(..., leases, ...)`
  signature + shrunken allowlist + new `test_the_runtime_sqlite_path_is_declared_once`
  failed (3 failures). GREEN after migrating `sidecar/stores.py` (one
  `PerRoot(RuntimeStores)` per facade), `app.py` (idempotency), `worker.py`
  (`build_worker` now receives `leases` instead of a state path) and
  `local_worker.py` (a violator the mapping missed). `sidecar/roots.state_path`
  removed. `atomic_write_text` for baseline promotion now comes from the
  composition root. Targeted suites (sidecar, local_worker, api, architecture)
  green; ruff and mypy clean.
- T4 done (commit 7450e634). Verified `create_production_worker*` had no caller in `src/` or
  docs (only tests) and that `compose_worker` always passes
  `application.observability`. RED: new
  `test_worker_composition_without_observability_stays_noop` + allowlist
  shrink failed; GREEN after deleting both factories, their tests, the
  sqlite imports and the `create_observability_from_env()` fallback in
  `WorkerComposition` (the integration test pinning that fallback removed).
  Targeted workers/integration/architecture/sidecar 241 passed; ruff, mypy clean.
- T5 done (commit b360db80). `ApplicationComposition` already exposed `directory_guard` /
  `release_lock`; cli modules now import `owned_directory_lock` /
  `directory_handle_guard` from `docs.composition` (re-exported, commented).
  `source_app.create_source_pipeline` no longer builds `MdNormalizeAdapter` /
  `AtomicFileAdapter` fallbacks: deps without them yield no pipeline. RED:
  allowlist deleted (violators asserted empty) + new
  `test_source_pipeline_needs_its_adapters_from_the_composition` failed;
  GREEN after the change. DEVIATION: the allowlist did not reach empty.
  `application/provenance.py` (lazy `import_module` subclass of the concrete
  infrastructure ledger, used by ~10 application services) remains as one
  named, justified, shrink-only `KNOWN_EXCEPTIONS` entry; removing it needs a
  provenance port + injection, which is out of T1-T5 scope. Suggest a new task.
  Targeted (architecture, cli, source commands, composition) 190 passed;
  ruff, mypy clean.
- Full-suite evidence: T1 3206 passed / 3 timing-flaky failures under load
  (plugins sdk, pass in isolation); T2 (side worktree, 70ea2b16) 3211 passed,
  6 skipped. Final commit b360db80 (T5): 3211 passed, 6 skipped.
- T5b done. RED: `KNOWN_EXCEPTIONS` and its shrink-only test deleted; the
  scan reported `application/provenance.py`. GREEN: `application/provenance.py`
  is now only `ProvenanceLedgerPort` (reusing the narrow-port idea of
  `build_manifest_service.ProvenanceLedgerPort`, widened to the six methods
  application calls) plus a `LedgerFactory` protocol with the ledger
  constructor signature. The v2-compat `verify_attestation` and
  `_without_optional_artifact_metadata` moved into
  `infrastructure/provenance/ledger.py` (the lazy subclass is gone).
  `composition.open_provenance_ledger` / `ApplicationComposition.provenance_ledger`
  is injected into `PackagePublicationService`, `assemble_pipeline_resources`,
  `StatusReader` (via `StatusService`, and `ApiApplication.status_reader` fed
  by the sidecar) and `document_app._promote_published_build`. The ledger
  was used by 3 src modules constructing it (not ~10); the rest only typed it.
  Tests import the concrete ledger from infrastructure. Targeted
  (architecture, unit/application, unit/api, sidecar, composition, cli,
  pipeline integration) 1078 passed; ruff, mypy clean.
- T6 done. RED: new `confine_or_raise` / `read_json_object` tests failed at
  import (ImportError). GREEN: `domain/paths.confine_or_raise(root, rel,
  make_error)` replaces the 4 confine+remap copies (`api/tool_routes`,
  `api/delivery_routes`, `workers/composition`, `plugins/registry`), each
  keeping its own error type (APIError 400 / ValueError / ManifestError).
  `domain/identity.read_json_object` (None on absent/unreadable/non-object)
  replaces the 3 matching read-then-check-dict copies in `sidecar/stores.py`.
  Deliberately NOT merged: `figure_resolver.read_json_fail_open` returns `{}`
  for an absent file and warns in Spanish (and `generate_visuals._read_json_fail_open`
  is a shape check layered ON it, not a copy); `composition._load_workspace_config`
  warns and does not check the shape; `sidecar/stores` collection store accepts
  a top-level list; `doc_crud_app`/`workspaces` raise or differ. Merging any of
  those would change semantics. Targeted domain/api/workers/plugins/sidecar/
  architecture 733 passed; ruff, mypy clean.
- T7 done. Per-port decisions (rg over src and tests):
  ContextRepository, DocxAssemblyPort, DocxAuditPort, EvidenceRepository,
  SectionRepository, SourceRepository: KEPT. Each is imported by application
  services (context/section, docx_assembly, format_audit, 7 evidence
  consumers, 5 section consumers, collection); inlining the adapter would
  make application import infrastructure, so the hexagonal rule wins (and
  test_context_service/test_context_gap_report do define a `read_topic` fake).
  FontSourcePort: REMOVED. Only `Pypdfium2TextEditAdapter` (infrastructure)
  used it, with one impl (`DejaVuFontSource`) and no test substitute; the
  adapter now types the optional parameter as `DejaVuFontSource` (infra to
  infra) and the contract text moved to the source's docstring, with a
  `# ponytail:` naming the upgrade path. RED/GREEN: new
  `tests/architecture/test_ports_have_consumers.py` (every domain port needs
  a consumer outside infrastructure) failed naming `font_source_port`, passes
  after. Its shrink-only allowlist names `blob_store`, `graph_store`,
  `plugin_executor` (runtime-store ports pinned by `test_runtime_ports.py`,
  outside the candidate list; flagged for a later decision).
  DocumentRepository/RegistryRepository/TemplateRepository: KEPT split. They
  are narrow interfaces consumed by different services (`DocumentService`
  takes registry and template separately; `test_repository_ports.py` pins
  each) and one class already implements all three, so merging would only
  widen every consumer. `PlatformSandboxProvider`: KEPT. It has no prod impl
  but it is the injection seam of `PluginRunner` (fail-closed: without a
  provider-issued attestation nothing counts as sandboxed) and
  `tests/unit/plugins/test_sdk.py` substitutes it with two fakes. Targeted
  architecture + pdf adapter + infrastructure + domain 1398 passed; ruff, mypy clean.
- T8 done. RED: `tests/unit/application/test_workspace_config.py` failed at
  collection (no `docs.application.workspace_config`). GREEN: the new module
  holds `load_workspace_config`, `WORKSPACE_CONFIG_FILENAME`, `deep_merge`,
  `expand_tokens`, `standard_tokens`, `computed_paths`,
  `apply_confirmed_placements`, `try_compile_template` and
  `rules_manifest_state` (no adapters; moved verbatim, underscore dropped).
  `composition.py` 833 -> ~700 lines and imports them; `doc_crud_app` now
  imports `WORKSPACE_CONFIG_FILENAME` from the new module (it was the only
  external user). The `try_compile_template` test moved with the function.
  Attribute types: `markdown_normalizer: MarkdownNormalizerPort`,
  `atomic_file_writer: AtomicFilePort`, `visual_renderers: dict[str,
  VisualRendererPort]`, `pdf_classifier: PdfClassifyPort | None`,
  `pdf_text_editor: PdfTextEditPort | None`, `pdf_render: PdfRenderPort | None`,
  `docx: DocumentRendererPort`, plus `context_repository: ContextRepository`,
  `source_repository: SourceRepository` and `rules_manifest_state` as a
  `Callable`; mypy clean with no ignores. `resolve_renderer` and
  `build_workspace` stay (the latter touches the registry adapter). Targeted
  composition/architecture/cli/workspace-config 170 passed; ruff, mypy clean.
- Full suite on 41ae57cf (side worktree, since removed): 3221 passed, 6
  skipped, 1 failed: `tests/unit/plugins/test_sdk.py::test_runner_enforces_measurable_scratch_limits_and_reports_usage`
  (PytestUnhandledThreadExceptionWarning in a plugin reader thread under load;
  the same file passes 32/32 in isolation, same flaky class as T1).
- T9 done. RED: `tests/unit/domain/test_theme.py` failed at collection (no
  `docs.domain.theme`). GREEN: the 7 theme dataclasses, `resolve_visual_theme`,
  `has_visual_theme` and `_theme_color` (now public `resolve_theme_color`) moved
  to `domain/theme.py`; only the adapter and one test imported them, both
  updated (no re-exports). Optional OOXML zip helpers NOT moved: they share
  `_parse_part` with the rest of the adapter, so moving them would only
  relocate the coupling. Targeted theme/infrastructure/docx/architecture 498
  passed; ruff, mypy clean.
- T10 done. Moved to `domain/pdf_layout.py` (all verified free of
  pdfium/ctypes): `styled` + `BASE14`, `line_start`, `line_x`, `outside`,
  `overlaps`, `union`, `missing_expected_lines`, `permitted_bounds`,
  `match_key`, `strip_subset_tag`, `drop_unmapped`, plus `ObjectSnapshot`,
  `Bounds`, `POST_WRITE_TOLERANCE_POINTS`. Call order in the adapter is
  untouched (read/write phase comments intact); `text_fitting` already covered
  nothing of these, so nothing duplicated. Adapter 813 -> ~660 lines. Tests:
  `tests/unit/domain/test_pdf_layout.py` (10) added AFTER the move (honest
  note: this was a verbatim move, so characterisation tests, no observed RED);
  the integration test now imports `ObjectSnapshot`/`missing_expected_lines`
  from the domain. Targeted pdf/translate/architecture/infrastructure 520
  passed; ruff check, mypy clean.
- T11 done. AGENTS.md section 9 "Where do I add X" (port/adapter, CLI
  command, API route, `RuntimeStores`, `confine_or_raise`/`read_json_object`,
  `application/workspace_config.py`, pure domain modules, and the two new
  architecture tests `test_ports_have_consumers` and
  `test_infrastructure_imports`). Inline route; docs-only, so no RED. Every
  named path/symbol was checked to exist. `test_agents_md_content.py` and the
  packaging test pass.
- Full suite on 395a6068: 3238 passed, 6 skipped, 0 failed. All tasks done; next: native review, then PR (user decision).
- T12 done. Allowlist deleted. RED: with `KNOWN_ORPHANS` removed the guard
  failed naming `blob_store`, `graph_store`, `plugin_executor`. Decisions:
  `blob_store` KEPT as a real seam (`InMemoryBlobStore` fake substitutes it;
  `ApiApplication.blob_store` was an untyped `Any` slot, now `BlobStore | None`,
  so the API layer is the consumer). `graph_store` KEPT likewise
  (`InMemoryGraphStore` fake; `ApiApplication.graph_store: GraphStore`);
  `graph_routes` keeps a local `Any` with a `# ponytail:` because
  `GraphQueryService` is typed on `SemanticGraphStore` while the host serves
  the runtime `Graph` (pre-existing mismatch the old `Any` hid). `plugin_executor`
  REMOVED: `PluginRunner` is the only implementation, nothing in src types
  against the Protocol and no fake substitutes it; the signature pin in
  `test_runtime_ports.py` now targets `PluginRunner.run` directly. No
  application/domain import of infrastructure added. Targeted
  architecture 131, domain+api+runtime-stores+vertical-journey 1383 passed, ruff, mypy clean. The removed port had drifted from the runner (it lacked `artifact_digest`); the pin now reflects the real signature.
