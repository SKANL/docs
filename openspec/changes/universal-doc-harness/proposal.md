# Proposal: universal-doc-harness

## Intent

Turn the thesis-specific ("tesina") DOCX tool into a format-agnostic, deterministic, idempotent **document-creation harness**. Applying Hashimoto's `Agent = Model + Harness`: the harness (Python CLI) owns all mechanical work — detection, routing, conversion, file writes, validation, naming, idempotency — while the AI model does only cognitive work (prose, curation judgment) via structured, auditable context slots. Today formats and "tesina" identifiers are hardcoded across domain/application, blocking reuse for any other document type.

## Scope

### In Scope
- **Ingest pipeline v1**: filetype detection (`filetype` lib + extension fallback) → router → per-type ingest for PDF (`opendataloader-pdf`), DOCX/ODT (pandoc + `--extract-media`), MD/TXT (frontmatter normalize).
- **Context files + index**: many small, single-purpose markdown files (keywords, tone, structure, writing style, formatting rules) in folders, plus ONE markdown index following Anthropic 3-level progressive disclosure. Harness writes structured slots with instructions; agent fills cognitive fields in a separate auditable step.
- **`DocumentRendererPort`** abstraction with DOCX as the only concrete adapter; extensibility proven by tests.
- **Clean break** from "tesina" naming — no migration (no production docs to protect).
- **Debt cleanup**: declare `docxcompose`; delete root `main.py`; split `cli/main.py` god-module into sub-apps; split fat `DocumentRepository` port; fix silent `except Exception` in `filesystem_source_repository.py`; add application-layer unit tests; de-duplicate `_sections_index`.

### Out of Scope
- HTML/EPUB ingest; PDF/HTML rendering adapters (future small changes).
- Harness auto-invoking the AI model — the agent step stays separate and auditable.
- Visual QA for non-DOCX formats.

## Capabilities

### New Capabilities
- `document-ingest`: detection, routing, and per-type source→markdown conversion.
- `context-curation`: small context-file generation + progressive-disclosure index.
- `document-render`: `DocumentRendererPort` + DOCX adapter, config-driven stage plan.

### Modified Capabilities
- `document-pipeline`: stage plan becomes data-driven; "tesina" sentinels removed.
- `asset-management`: generalize `.docx`-only asset validation to an asset-kind concept.

## Approach

Format registry resolved by template output format in the composition root; `domain/pipeline.py` orders stage *names* supplied by config (no format branching). Ingest reuses the trusted `PipelineService` stage-callable + fail-fast pattern, `ToolResolverPort` for pandoc, and the existing `_`-prefix/index convention. Sequence: (1) rename sentinels + generalize assets, (2) renderer registry, (3) ingest → context files/index.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `domain/pipeline.py` | Modified | Data-driven stage plan |
| `application/docx_assembly.py` | Modified | Behind `DocumentRendererPort` |
| `domain/ports/asset_repository.py`, `application/asset.py` | Modified | Generalize `glob_docx` |
| `cli/main.py` | Modified | Split god-module into sub-apps |
| `infrastructure/persistence/filesystem_source_repository.py` | Modified | Fix silent except; reuse index convention |
| `pyproject.toml` | Modified | Declare `docxcompose`; add `filetype`, `opendataloader-pdf` |
| root `main.py` | Removed | Dead entrypoint |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `opendataloader-pdf` maturity unverified | Med | Add explicit verification task before locking dep |
| Context-file granularity is new design surface | Med | Resolve chunking rules in sdd-design |
| God-module split churn | Med | Split before/with new commands; slice PRs |

## Rollback Plan

Each auto-chain slice has its own start/finish/verification/rollback. Revert per slice via its PR; ports are additive so reverting the renderer registry restores the DOCX-only path. No data migration means rollback needs no state repair.

## Dependencies

- `filetype` (pure Python), `opendataloader-pdf` (verify first), `docxcompose` (declare existing), pandoc (already required).

## Success Criteria

- [ ] Non-DOCX sources (PDF/DOCX/ODT/MD/TXT) ingest to markdown deterministically and idempotently.
- [ ] Context files + one progressive-disclosure index generated as fillable slots.
- [ ] DOCX renders through `DocumentRendererPort`; a second-format test proves extensibility.
- [ ] No "tesina" identifiers remain; debt items closed; application-layer unit tests added.
- [ ] Full pipeline reproducible: same inputs → identical outputs.
