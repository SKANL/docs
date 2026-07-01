# Migration Roadmap — tesina_harness.py → Hexagonal Architecture

Source: `C:\code\harness-projects\old-se-debe-migrar\tesina\harness\scripts\tesina_harness.py` (3951 lines).
Target: `C:\code\harness-projects\docs` (uv-managed, Typer + Pydantic v2, Pragmatic Hexagonal — domain/application/infrastructure/cli).

This roadmap is a scope inventory, not a detailed task plan. Each remaining slice gets its own
`plans/<date>-slice-N-<name>.md` with verbatim legacy code blocks and a task breakdown, exactly like
Slices 1-6.

## Completed

| # | Slice | Scope |
|---|-------|-------|
| 1 | Foundations | Result value objects, slug validation, Template/Document models, DocumentRepository + JSON adapter, DocumentService (create/list/current/use/rename/delete) |
| 2 | Context | Context completion rules, topic markdown render/parse, ContextRepository + adapter, index regeneration, ContextService (status/set/show/remove/ingest), requests file render/parse |
| 3 | Rules + Review | Issue/ReviewResult value objects, markdown text utilities, APA7 extraction, review_section_contract/apa7_text/section_text/rules/cross_consistency (all pure) |
| 4 | Evidence | ManualFileFact/TraceabilityFact/build_manifest (pure), EvidenceRepository + JSON adapter, EvidenceService.build_rules |
| 5 | Sections | infer_section_id_from_path (pure), SectionRepository (read-only) + JSON adapter, ReviewService.review_document |
| 6 | Pipeline | ManualHashFact/build_rules_hash_payload/with_frontmatter/default_section_metadata/apply_stamp (pure), EvidenceRepository.hash_text + SectionRepository.write_section, EvidenceService.rules_hash/contract_hash/manifest_hash, ReviewService.stamp_section |
| 7 | Collection | classify_source/parse_gh_issues/dedupe_facts/extract_github_repo (pure), SourceRepository (new port, glob+subprocess) + FilesystemSourceRepository adapter, CollectionService.collect_sources/collect_issues/collect_code_evidence |
| 8 | Section Rendering | `apply_keyword_bold`/`render_toc_section`/`render_contract_scaffold`/`render_section_draft`/table+heading extraction helpers (pure, domain/section_rendering.py), `SectionContract.toc`/`references_list` typed fields, `EvidenceService.load_manifest_facts`/`render_fact_ledger`, `SectionRepository.write_proposal_section` (port + JSON adapter), `ReviewService.build_section`/`resolve_section_path` |
| 9 | Context Packing & Assets | `keyword_set`/`matches_keywords` (pure), `AssetRepository` (new port) + `FilesystemAssetRepository` adapter + `Workspace.assets_dir`, `AssetService` (asset_path/add_asset/list_assets/remove_asset), `SectionRepository.context_pack_path`/`document_context_pack_path`/`write_context_pack` (port + JSON adapter), `ReviewService.review_section`, `ContextPackService` (new — first service-composes-service: `pack_context`/`pack_context_document`) |
| 10 | Format Audit (DOCX) | `docx_structure.py` (pure: `structure_parts`/`resolve_part_text`/`non_cover_margin_emu`/`margins_match`), `DocxAuditPort` (new port) + `PythonDocxAuditAdapter` (infrastructure — deliberate exception: most orchestration logic lives in the adapter, not split into app-layer judgment, since the legacy traversal has no separable raw-fact/judgment boundary), `FormatAuditService.audit_format` (new service). New dependency: `python-docx`. Forward-pulled `_structure_parts`/`_resolve_part_text`/`paragraph_has_numbering` from Slice 11's range — Slice 11 must not re-port these |

## Remaining

| # | Slice | Legacy lines | Size | Notes |
|---|-------|--------------|------|-------|
| 11 | DOCX Assembly | 2297-2862 (~565 lines, minus 3 helpers already satisfied by Slice 10) | large — likely splits into "core" + "layout/TOC/numbering" when planned in detail | `build_docx` + ~15 helpers (structure parts, cover doc, main doc, asset embedding, assemble_structure, page numbering, TOC, styles). Do NOT re-port `_structure_parts`/`_resolve_part_text`/`paragraph_has_numbering` — already satisfied by Slice 10 |
| 12 | QA & PDF Rendering | 2862-3079 | large | `qa_docx`/`run_documents_audits`/`render_docx_to_pdf`/`render_docx_pages`/`render_pdf_with_pypdfium`/`render_qa_report`. Depends on external tools (pandoc/libreoffice/pypdfium2). **User decision (2026-06-21): the PNG-per-page rendering pipeline (`render_docx_pages`/`render_pdf_with_pypdfium`/pdftoppm fallback) is explicitly OUT of scope for this migration — will be reimplemented differently later. Port everything else in this slice; skip/stub the PNG generation path.** |
| 13 | Doctor + Corrections | 2185-2296 + 3080-3151 | small-medium | `run_doctor` validates everything built so far (hence near the end); `apply_corrections`/`parse_simple_yaml` bundled in to avoid a single-function slice |
| 14 | Pipeline & Run Logging | 3152-3354 | medium | Orchestrates everything above: `run_pipeline`/`verify_all`/`log_run`/`_pipeline_stages`/`list_runs`. Must come near the end since it composes all prior services |
| 15 | CLI Surface | 3355-3951 | large | All `command_*` functions + argparse → Typer. New dependency: `typer` |

**Total remaining: 5 slices** (11-15). Slice 11 (Assembly) may split into two when planned in detail given its size, which would make the real remaining count 5 or 6.

## Open scope notes carried from Slice 6

- `source_hash`/`prompt_hash` remain deferred until Slice 7/9 model `context_dir`/`prompts_dir` config concepts.
- `generated_metadata_changed` (build_section-only helper) ports alongside `build_section` in Slice 8, not before — it's dead code without its caller.
