# Design: universal-doc-harness

## Technical Approach

Extend three patterns the codebase already trusts — Protocol ports, the `Deps` composition root, and `PipelineService` stage-callables — so no new architectural idiom is introduced. The harness owns all mechanical work (detect, route, convert, write, hash, name); the AI model only fills clearly-marked cognitive slots in context files. Output format and stage plan become config data, not hardcoded literals. `Template` already sets `extra="allow"`, so a new `output.format` key (default `"docx"`) is additive and back-compatible.

## Architecture Decisions

### Decision: Renderer registry, config-driven stage plan (explore A-3)
**Choice**: New `DocumentRendererPort` Protocol; a `RENDERERS: dict[str, DocumentRendererPort]` map in `Deps` keyed by `config["output"]["format"]`. `DocxAssemblyService` is renamed to `DocxRendererAdapter` with behavior unchanged (only the hardcoded `tesina-draft.docx`/`tesina-body.docx` names move to config). `domain/pipeline.py:pipeline_stage_plan` stops holding `_ASSEMBLE_STAGES` literals and instead orders stage-name tuples supplied by the resolved renderer.
**Alternatives**: (A-2) pandoc-as-universal-renderer — rejected: still needs per-format post-assembly (cover, TOC, embeds), so it collapses into A-3 with less clarity. Keep-hardcoded — rejected: blocks the whole goal.
**Rationale**: Same DIP already proven by `DocxAssemblyPort`; keeps `domain/pipeline.py` pure (orders names only, zero format knowledge); each new format is additive/open-closed.

### Decision: Ingest as new stage-set reusing the stage-callable pattern (explore B-3)
**Choice**: New stage_set `ingest` = `detect-inbox` → `route-inbox` → `ingest-<type>`. Detection via `filetype` lib + extension fallback (reject `python-magic`: libmagic native dep, poor Windows fit). pandoc covers docx/odt/html/epub through the existing `ToolResolverPort`; `opendataloader-pdf` behind a new port for PDF; md/txt normalized via existing `split_frontmatter`.
**Alternatives**: extension-only routing — rejected: fails the "detect each type" goal on wrong/missing extensions. Standalone script outside the pipeline — rejected: loses `log_run` audit trail and fail-fast machinery.
**Rationale**: Additive stages, no rewrite; reuses fail-fast booleans, per-stage timing, and the audit log already trusted for `prep`/`assemble`.

### Decision: Idempotency via content hash + deterministic output paths
**Choice**: Each ingest writes `sections/ingested/<stem>-<sha8>.md` where `sha8` is the first 8 hex of the source sha256, recorded in `inbox/_detection.json`. Re-run with unchanged hash is a no-op. Unknown/unsupported types are recorded with `status: "unsupported"` and reported, never fatal.
**Rationale**: Mirrors the hashing `EvidenceService` already uses; "same inputs → identical outputs" becomes structural, satisfying the success criterion.

### Decision: Deterministic context-file skeletons with marked agent-fill slots
**Choice**: Harness writes byte-identical skeletons from pure functions over ingested markdown; agent cognitive content lives only inside explicit `AGENT-FILL` blocks that the harness preserves (idempotent merge) on re-run and never regenerates destructively.
**Rationale**: Separates deterministic mechanical output from auditable cognitive edits — Hashimoto's harness principle; enables a byte-comparison determinism test.

### Decision: Segregate the fat DocumentRepository port (ISP)
**Choice**: Split into `RegistryRepository` (`active_id`), `DocumentRepository` (`read_document`), `TemplateRepository` (`load_template`). One `JsonDocumentRepository` adapter may still implement all three; consumers depend on the narrow port they use.
**Rationale**: Fixes the flagged fat-port debt without a data migration.

## Data Flow

    inbox/*  ──detect-inbox──▶ _detection.json ──route-inbox──▶ ingest-<type>
      (filetype+ext)                                    │ (pandoc | opendataloader-pdf | md-normalize)
                                                         ▼
                                        sections/ingested/<stem>-<sha8>.md
                                                         │
                                     build-context-files │ (deterministic skeleton + AGENT-FILL)
                                                         ▼
                              context/{keywords,tone,structure,writing-style,formatting-rules}.md
                                     build-context-index │  + context/references/<topic>.md
                                                         ▼
                                        context/index.md  (Anthropic 3-level: entry→body→references)
                                                         │  [agent fills slots — separate audited step]
                                                         ▼
                     RENDERERS[config.output.format] ──▶ build → audit → qa (stage plan from renderer)

## Context Layout & Index Contract

```
doc_root/context/
  index.md            # Level 1: one line per file — "what it is | load when…"
  _requests.md        # existing "_"-prefix = not for direct load (kept)
  keywords.md tone.md structure.md writing-style.md formatting-rules.md   # Level 2 bodies
  references/<topic>.md    # Level 3: bulk, loaded only on demand
```
Slot skeleton (deterministic; agent edits only inside the block):
```markdown
# Keywords
<!-- HARNESS skeleton — edit only AGENT-FILL blocks -->
## Extracted (auto)
- <term>
<!-- AGENT-FILL:curated-keywords START -->
<!-- Fill: 5–10 canonical keywords -->
<!-- AGENT-FILL:curated-keywords END -->
```
`index.md` reuses the existing `read_context_texts` convention (skips `index.md` and `_`-prefixed files), replacing the JSON-only `context/index.json` with an agent-readable markdown index.

> [ADDITIVE NOTE, PR8 task 8.1: the literal filename above is aspirational and
> was NOT what shipped. `application/context_files.py:build_context_index`
> and the pre-existing, unrelated `JsonContextRepository.regenerate_index`
> (Topic/Q&A context-schema subsystem behind `context status/elicit/ingest/
> set/rm`) both targeted `context/index.md` with two incompatible formats —
> a collision flagged by PR7's fresh-context review. PR8 namespaces rather
> than consolidates: the Topic/Q&A subsystem keeps `context/index.md`
> untouched; the new progressive-disclosure index writes to
> `context/curated-index.md` (`CURATED_INDEX_FILENAME`). Consolidating the
> two was explicitly out of scope (see tasks.md 7.6's own additive note) —
> they serve different purposes with incompatible content shapes. Locked in
> by `tests/integration/test_pipeline_service.py::
> test_run_pipeline_ingest_stage_set_writes_curated_index_without_touching_topic_qa_index`.]

## Interfaces / Contracts

```python
class DocumentRendererPort(Protocol):
    output_format: str
    def stage_plan(self) -> list[tuple[str, bool]]: ...          # (stage-name, fail_fast)
    def build(self, doc_id: str, config: dict, output: Path | None = None) -> Path: ...

class SourceTypeDetectorPort(Protocol):
    def detect(self, path: Path) -> str: ...                     # kind id, "" if unknown

class SourceIngestPort(Protocol):
    def ingest(self, src: Path, out_dir: Path) -> Path: ...      # → deterministic .md path
    # [ADDITIVE NOTE, tech-debt closeout D6: PR6 fresh-review remediation grew
    # a required third `kind: str` parameter — the port's actual, tested
    # contract is `ingest(src, out_dir, kind)`. See tasks.md task 6.7.]

# domain/pipeline.py — pure ordering, no format literals
def pipeline_stage_plan(stage_set, prep, assemble, ingest) -> list[tuple[str, bool]]: ...
# [ADDITIVE NOTE, PR8 task 8.1: this signature sketch was NOT what shipped.
# `prep` never became a parameter (PR4 already fixed it as a module
# constant, `_PREP_STAGES`), and `ingest` landed the same way: a second
# module constant, `_INGEST_STAGES`, returned directly for
# `pipeline_stage_plan("ingest")`. Ingest/context-file stage names are just
# as format-agnostic as `prep` -- they never vary by output format -- so a
# caller-supplied parameter would have been unnecessary indirection. Only
# `assemble` is genuinely caller-supplied (it varies by the resolved
# `DocumentRendererPort`). The actual, tested signature stayed
# `pipeline_stage_plan(stage_set, assemble=None)`.]
```
Asset generalization: `AssetRepository.glob_docx` → `glob_assets(kind)`; `AssetService` validates by configurable asset-kind, not hardcoded `.docx`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `domain/ports/document_renderer_port.py` | Create | Renderer Protocol |
| `domain/ports/source_type_detector_port.py`, `source_ingest_port.py` | Create | Ingest ports |
| `domain/ports/document_repository.py` (split into registry/document/template) | Modify | ISP segregation |
| `application/ingest.py` | Create | IngestService (detect→route→ingest) |
| `application/context_files.py` | Create | Skeleton + index generation |
| `infrastructure/ingest/` (filetype detector, pandoc, opendataloader-pdf, md adapters) | Create | Ingest adapters |
| `application/docx_assembly.py` → `DocxRendererAdapter` | Modify | Rename behind port; config-driven output names |
| `domain/pipeline.py` | Modify | Data-driven stage plan (no format literals) |
| `application/pipeline.py` | Modify | Add ingest/context stage callables; drop `_DRAFT_DOCX_NAME` |
| `application/asset.py`, `domain/ports/asset_repository.py` | Modify | Generalize `glob_docx`→asset-kind |
| `infrastructure/persistence/filesystem_source_repository.py` | Modify | Fix silent `except Exception`; reuse index convention |
| `cli/_shared.py` | Modify | `RENDERERS` registry; register ingest adapters; `output_format` |
| `cli/main.py` → `cli/commands/*_app.py` | Modify | Split god-module into sub-Typer apps |
| Sentinel strings (`evidence.py`, `collection.py`, `rules.py`, `sections.py`, `review.py`, `section_rendering.py`) | Modify | Remove `"tesina"` identifiers |
| `pyproject.toml` | Modify | Declare `docxcompose`; add `filetype`, `opendataloader-pdf` |
| root `main.py` | Delete | Dead entrypoint |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | IngestService routing, detector ext-fallback, registry resolution, skeleton builder | fake ports, `uv run pytest`, strict TDD (test first) |
| Extensibility | second format proves open-closed | register a fake `"txt"` renderer in a test registry; pipeline resolves its stage plan without editing `domain/pipeline.py` |
| Determinism | same sources → identical bytes | double-run byte comparison of ingested `.md` and context skeletons |
| Regression | DOCX path unchanged | existing integration tests (`test_docx_assembly_service`) must stay green |

## Migration / Rollout

No data migration. Clean break from `"tesina"` naming (no production docs). `managed_by: "tesina-harness"` sentinel is an ownership gate: renaming it means existing on-disk sentinels stop matching — acceptable given no protected docs, but the rename must be a single atomic slice. Ports are additive; reverting the renderer registry restores the DOCX-only path.

## Open Questions

- [ ] Verify `opendataloader-pdf` maturity before locking the dependency (proposal risk).
- [ ] PDF/HTML visual QA parity — `LibreOfficeQaAdapter` is DOCX/ODT-only; treat as follow-up non-goal.
