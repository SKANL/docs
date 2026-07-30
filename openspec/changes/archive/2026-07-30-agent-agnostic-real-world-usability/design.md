# Design: Agent-Agnostic Real-World Usability

> Technical design (the architectural HOW). Steps/tasks are owned by
> `sdd-tasks`. Every decision below is grounded in current on-disk code with
> `file:line` citations. Bound decisions 1–3 from the proposal are inputs, not
> re-litigated here.

## 1. Architecture approach

The harness is hexagonal (`domain/` pure logic + `ports/`, `application/`
services on ports, `infrastructure/` adapters, `cli/` Typer + composition root
in `cli/_shared.py`). This change adds **zero new architectural layers**. Every
item lands on one of four existing seams:

| Seam | Where | Items landing here |
|------|-------|--------------------|
| Composition root | `Deps.__init__` (`cli/_shared.py:77`) + `build_workspace` (`:64`) | A (config), F (PDF wiring) |
| Pure domain function extension | `domain/source_role.py`, `domain/rules.py`, new `domain/*` modules | D, H, J, K, M |
| Application service method | `DoctorService` (`application/doctor.py:18`), `ContextService.build_gap_report` (`application/context.py:130`), `IngestService` (`application/ingest.py`) | E, G, K, L |
| CLI command | `doc_app`, `template_app`, new `core_app` command | B, C, I |

Two governing principles, both already visible in the codebase and preserved:

- **I/O in adapters, judgment in pure functions.** `classify()`
  (`source_role.py:51`) is explicitly "zero I/O, zero randomness". Item D keeps
  that: a new *adapter* reads file bytes and produces content-signal STRINGS;
  the pure classifier consumes strings only. Same split as the existing
  `image_metadata` port injected into `IngestService` (`ingest.py:145`).
- **Fail-open, never-silent.** The `ingest.py` walk already reports every
  ignored/empty/error path instead of dropping it (`_walk_inbox:204`,
  `_ingest_one_safely:309`). Items D/E/K extend the same contract: low-confidence
  and conflicting inputs are *queued/WARNed with next-steps*, never silently
  defaulted.

### Reproducibility boundary (item M) — the design principle that governs all others

The section `.md` files (agent-authored prose) are the **durable source of
truth**; the `.docx` is a **deterministic pure function of them + the figure
catalog + the template**. Byte-determinism is asserted on the BUILD, not the
prose. Concretely this constrains every other item:

- Anything that writes bytes (config file, provisioned templates, rendered PDF
  pages, numbered captions) MUST be a deterministic function of its inputs — no
  timestamps, no wall-clock, no dict-iteration-order dependence. Any new
  `.docx`/zip writer still terminates in
  `infrastructure/docx/deterministic_zip.py:normalize_docx_zip_timestamps`
  (per repo CLAUDE.md).
- The numbering pass (H) is a pure rewrite over ordered section text → the same
  sections always yield the same numbers.
- Item M ships as a spec statement in `openspec/specs/document-pipeline/spec.md`
  and one paragraph in `AGENTS.md` (item B) — no code.

---

## 2. Per-item design (A–M)

See openspec/changes/archive/2026-07-30-agent-agnostic-real-world-usability/design.md for full content

[Full content preserved in archive folder]

---

## 3. PR slicing (chained, stacked-to-main, ≤400 lines each)

Mechanical core first (each independently revertable and degrade-safe), guided
layer second. Order reflects dependency, not just the proposal's suggested list.

Ten slices rather than nine: G+K genuinely co-locate in ingest (slice 8), and I
depends on that report, so folding I into 8 would blow the ≤400-line budget.
`sdd-tasks` owns final boundaries and per-slice forecasts.

---

## 4. Determinism & edge-case risks

| Risk | Where | Mitigation |
|------|-------|-----------|
| Rendered PDF pages vary across pypdfium2/toolchain versions | F | Catalog sorts by `id`; adapter names are stable; pin `pypdfium2`/`pillow` ranges in `pyproject.toml`; render is gated to vector-only PDFs so raster-extraction machines and render machines don't double-count. Golden byte test covers the deterministic-inputs case only. |
| Numbering non-determinism if section/in-text order isn't total | H | `number_and_resolve` numbers in the exact `sorted(sections, key=order)` order `build` already uses then first-appearance in text — a total order. Unknown `[[ref:]]` → explicit `?` + WARN, never a silent variable output. |
| Content probe reads differ by platform/locale | D | Case-fold tokens; ASCII byte-order sort; probe failures → empty signals (fail-open), so classification degrades to folder-lexicon-only, never errors. |
| Malformed `docs.config.json` bricks every command | A | `build_workspace` best-effort parse; malformed → WARN + ignore, fall back to env/default (fail-open). Covered by a test with a corrupt file. |
| Review-precision fix regresses a genuine catch | J | Each fix ships paired positive+negative fixtures; characterization tests guard existing behavior. |
| Package data not shipped in wheel | B, C | A build+install test asserts `docs guide` and `template list --available` work from the installed wheel, not just the source tree. |
| `ContentProbePort` needed by both slice 1 (E) and slice 4 (D) | ordering | Land the port + adapter in whichever slice merges first (recommend slice 1's auto-detect uses a minimal probe, slice 4 extends it). |
| Fail-open hides a genuinely broken run | E, G | Clearly-marked gaps + intake report + finish-checklist; `--strict` restores hard-fail. |

---
