# Design — Migrating the Document Harness to a Hexagonal Architecture

- **Date:** 2026-06-19
- **Status:** Approved (design phase)
- **Target project:** `docs/` (uv-managed Python project)
- **Source:** `old-se-debe-migrar/tesina/harness/` (legacy monolith)

## 1. Context & Problem

The legacy "document harness" is a working tool that applies *harness engineering*
(the harness serves the agent; it never calls an LLM). It provides curated context,
deterministic gates, idempotency by content hashes, and run observability for
producing audited Word documents.

The product design is solid. The **code** is not:

- A single **3,951-line file** (`scripts/tesina_harness.py`) holding ~180 free
  functions and 4 dataclasses.
- Domain logic (rules, reviews, APA7, cross-consistency, hashing) is **fused** to
  infrastructure (`python-docx`, `pandoc`, `LibreOffice`, `git`, `gh`) and to the
  CLI (`argparse`).
- The pervasive `dict[str, Any]` "config" object is passed through almost every
  function — no types, no discoverability, no validation.
- **Global mutable state** (module-level `DOCUMENTS_DIR`, `REGISTRY_PATH`) forces
  tests to `mock.patch.object(...)` — a dependency-injection smell.

These properties make the code hard to read, hard to test in isolation, and hard
to change without fear of regressions.

## 2. Goals & Non-Goals

### Goals

- Preserve **all current capabilities** (functional parity of behavior and artifacts).
- Allow **UX improvements** to command ergonomics where there is a clear benefit.
- Apply **SOLID** (one reason to change per module) and **KISS** (ports only at the
  boundaries, no ceremony where it adds nothing).
- Make the domain logic **testable without any external binary**.
- Ship a **uv-native, cross-platform** CLI; remove the legacy bootstrap layer.

### Non-Goals

- Migrating the in-progress `sabatina` workspace. Only the **engine + templates**
  move. `sabatina` stays in the old project. Characterization fixtures are minimal,
  synthetic, and template-derived — not the real `sabatina` content.
- Changing the external document toolchain (pandoc / LibreOffice / gh remain).
- Rewriting the product concept. This is a re-architecture, not a redesign.

## 3. Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Pragmatic Hexagonal (Ports & Adapters)** | Separate by reason-to-change; isolate heavy/risky binaries behind ports. |
| 2 | **uv-native cross-platform CLI** (`docs <command>` via `[project.scripts]`) | Drop `tesina.ps1` + `setup_env.ps1`; uv manages venv + deps. |
| 3 | **Engine + templates only** | Lower risk; validate the engine in isolation. |
| 4 | **Parity of capabilities + UX improvements** | Keep every capability; improve ergonomics where it clearly helps. |
| 5 | **Typer + Pydantic v2** | Type-hints-to-CLI ergonomics; boundary validation of templates/config. |
| 6 | **Strict TDD + characterization tests** | Tests lead; golden-output tests guarantee parity against the legacy tool. |

## 4. Architecture

`src/` layout. Dependencies point **inward**: `cli → application → domain`;
`infrastructure → domain` (implements ports). The domain depends on nothing
external.

```
docs/
├─ pyproject.toml              # [project.scripts] docs = "docs.cli.app:main"
├─ src/docs/
│  ├─ domain/                  # ❶ PURE — no I/O, no python-docx, no subprocess
│  │  ├─ models/               #   Typed value objects (replace dict[str, Any])
│  │  │  ├─ template.py        #     Template, ContextSchema, Topic, Field
│  │  │  ├─ document.py        #     Document, Section, SectionContract, StructureBlock
│  │  │  └─ result.py          #     Issue, ReviewResult, Severity, DoctorResult
│  │  ├─ review/
│  │  │  ├─ section.py         #     per-section review (pure)
│  │  │  ├─ document.py        #     cross-consistency / coherence (pure)
│  │  │  └─ apa7.py            #     citation/reference checks (pure)
│  │  ├─ rules.py              #   normative rules: voice, subjective terms, privacy
│  │  ├─ context.py            #   completion / missing fields (pure calculation)
│  │  ├─ hashing.py            #   sha256, frontmatter, idempotency hashes
│  │  └─ ports/                #   Protocols the application depends on
│  │     ├─ document_repository.py · docx_writer.py · pdf_renderer.py
│  │     ├─ evidence_source.py · process_runner.py · clock.py
│  ├─ application/             # ❷ Use cases (orchestrate domain + ports)
│  │  ├─ documents.py          #   doc CRUD (new/use/rename/delete/list)
│  │  ├─ context.py            #   status/elicit/ingest/set
│  │  ├─ sections.py           #   build_section / pack_context / stamp_section
│  │  ├─ evidence.py           #   collect_sources/issues/code + build_ledger
│  │  ├─ review.py             #   review_rules/section/document + verify
│  │  ├─ assembly.py           #   build_docx / format_audit / qa_docx
│  │  ├─ corrections.py        #   apply_corrections
│  │  └─ pipeline.py           #   orchestration + runs/observability
│  ├─ infrastructure/          # ❸ Adapters implementing ports
│  │  ├─ persistence/          #   JSON repos: registry, document, templates
│  │  ├─ docx/                 #   python-docx writer, structure, TOC, pagination, margins
│  │  ├─ rendering/            #   pandoc · libreoffice · pypdfium
│  │  ├─ vcs/                  #   git facts · gh issues
│  │  └─ system/               #   executable resolution · clock · filesystem
│  └─ cli/                     # ❹ Thin input adapter (Typer)
│     ├─ app.py                #   main(), command registration
│     └─ commands/             #   handlers → call application services
└─ tests/
   ├─ unit/                    # pure domain (fast, no binaries)
   ├─ integration/             # application + real adapters
   └─ characterization/        # golden output vs legacy harness (parity)
```

### 4.1 Layer responsibilities

- **Domain** — pure functions and frozen value objects. Knows the rules of the
  document (voice, APA7, contracts, coherence, hashing). Knows *nothing* about
  files, docx, or subprocesses. Fully unit-testable.
- **Application** — one use case per current command group. Orchestrates the
  domain and talks to the outside world *only through ports*.
- **Infrastructure** — concrete adapters. The only place imports of `python-docx`,
  `subprocess`, `git`, `gh`, and the filesystem are allowed.
- **CLI** — translates args to use-case calls and renders results (text/`--json`).
  No business logic.

### 4.2 Ports (the five external boundaries)

| Port | Implemented by | Replaces (legacy) |
|------|----------------|-------------------|
| `DocumentRepository` | `infrastructure/persistence` | global `DOCUMENTS_DIR`, registry/doc/template loaders |
| `DocxWriter` | `infrastructure/docx` | direct `python-docx` calls scattered through assembly |
| `PdfRenderer` | `infrastructure/rendering` | pandoc + LibreOffice + pypdfium subprocess calls |
| `EvidenceSource` | `infrastructure/vcs` | `git` and `gh` subprocess calls |
| `ProcessRunner` / `Clock` | `infrastructure/system` | `subprocess`, executable resolution, timestamps |

With these, the domain and review logic run in tests with **zero binaries**.

## 5. Typed Models (the biggest maintainability win)

Templates and document config are parsed **once at the boundary** (a Pydantic
adapter in `infrastructure/persistence`) into frozen models. The domain receives
typed objects, never raw dicts.

- `Template` (project_defaults, normative, format, apa7, privacy, strict_policy,
  cross_consistency, context_schema, sections, section_contracts, structure).
- `Document` (id, title, template ref, per-doc resolved paths, sections).
- Result types: `Issue(severity, code, message, ...)`, `ReviewResult(passed, issues)`,
  `DoctorResult`, `Severity` enum.

Validation (required fields, regex patterns, enum values) happens at parse time, so
the rest of the system trusts its inputs. This removes the `dict[str, Any]` smell.

## 6. Data & Artifact Compatibility

The new engine must read/write the **same on-disk artifacts** the legacy tool used,
so existing template JSONs and the documented workspace layout remain valid:

- `templates/<type>.json` (carried over verbatim).
- `documents/<id>/` workspace layout (`document.json`, `context/`, `sections/`,
  `assets/`, `output/`, `runs/`) and `registry.json`.
- Section frontmatter hashes (`section_id`, `contract_hash`, `rules_hash`,
  `source_manifest_hash`, `prompt_hash`, `body_hash`) preserved so idempotency and
  human-edit detection keep working.

Hash computation is ported exactly (characterization tests pin the values).

## 7. Testing Strategy (Strict TDD)

A test pyramid, tests written before implementation:

1. **Unit (domain)** — fast, pure, no binaries. Covers rules, review, APA7,
   coherence, context completion, hashing.
2. **Integration (application + infra)** — adapters against temp workspaces and,
   where needed, real binaries (docx assembly, pandoc) behind markers.
3. **Characterization (parity)** — run the **legacy** harness on a fixed input and
   assert the new engine produces equivalent output (normalized for timestamps and
   non-deterministic fields). This is the parity guarantee.

No global-state monkeypatching: tests construct a real temp `Workspace` and inject it.

## 8. Migration Strategy

**Vertical slices, never big-bang.** Recommended order (each slice: characterize
legacy → write tests → implement clean → green):

1. Foundations: typed models + `DocumentRepository` + doc CRUD + registry.
2. Context: schema, completion, elicit/ingest, set/show.
3. Rules + review (section, APA7) — pure domain, highest test value.
4. Evidence: collect sources/issues/code, build ledger.
5. Sections: build_section, render, contract scaffold, pack_context, stamp.
6. Cross-consistency: review_document (coherence.*).
7. Assembly: build_docx, structure blocks, pagination, TOC, margins, embeds.
8. Format audit + QA (docx → pdf → png), corrections.
9. Pipeline + verify + runs/history (orchestration on top).
10. CLI surface (Typer) wiring every use case; apply agreed UX improvements last.

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| DOCX assembly fidelity drift (margins, pagination, TOC) | Characterization tests on generated `.docx`/OOXML parts; keep adapter logic ported 1:1 first, refactor after green. |
| External binaries unavailable in CI | Mark binary-dependent tests; domain tests never need them. |
| Hidden coupling in legacy `config` dict | Typed models surface every field explicitly during parsing; unknown fields fail fast. |
| Hash incompatibility breaks idempotency | Pin legacy hash outputs as golden values before refactoring. |

## 10. Open Questions

- Exact UX improvements to the command surface (deferred to slice 10; parity first).
- Whether characterization tests invoke the legacy script directly or compare to
  captured golden artifacts checked into `tests/characterization/fixtures/`.
