# Docs Harness v2 QA

QA is layered. A green command means the applicable runtime contracts passed; it does not mean every optional visual tool was available.

## Visual baselines

Visual snapshots are opt-in. Configure a baseline directory and an explicit
similarity tolerance in the document configuration:

```json
{
  "visual_qa": {
    "baseline_dir": "qa/baselines",
    "minimum_similarity": 0.75
  }
}
```

QA regenerates the execution's preview PNGs, removing obsolete pages before
comparison. It compares each page with the same-named baseline without modifying
the baseline directory. Preview and baseline directories must not overlap. It reports `visual.baseline_changed`,
`visual.baseline_missing`, `visual.baseline_extra_page`, or
`visual.baseline_unreadable` with the affected page. Draft mode reports these
as warnings; strict and release mode make them blocking errors. Updating a
baseline is an explicit authored operation outside verification.

## Local checks

```bash
uv sync --locked
uv run ruff check .
uv run mypy
uv run pytest -q --cov=src --cov-report=term-missing --cov-fail-under=93
uv run pytest tests/architecture -q
```

Use `uv run docs doctor` to see optional executables and their versions. For a document, run `document verify` for the requested formats and inspect the JSON stage results, warnings, capabilities, and verification payload.

## Verification layers

- **Contract QA:** stage definitions, artifact names, dependencies, and outcomes are deterministic and validated before execution.
- **Source QA:** ingest, normalization, and compiled structure are reported as `docs.sources/v2` and `docs.structure/v2` artifacts.
- **DOCX QA:** format audit plus rendered `QaService` findings through the existing
  `QaRenderPort`, including configured baselines and required previews.
- **HTML QA:** UTF-8 decoding and exactly one HTML root and body root.
- **PDF QA:** `%PDF-` signature, readable reopen, at least one page, and valid page render dimensions.
- **Provenance QA:** source/output hashes and manifest attestation are recorded only after accepted execution.
- **Publication QA:** strict/release policy, manifest identity, current input identity, attestation, containment, and atomic transform all pass.

### Injectable multiformat review service

`ReviewStageService` accepts `render_verification=RenderVerificationService(port)`.
The CLI injects the existing `RenderVerificationAdapter` for HTML/PDF and
`qa=QaService(...)` for DOCX visual review. `QaService.inspect_docx` returns
structured findings and a durable report; `qa_docx` retains its Path-returning
compatibility API. DOCX visual review keeps format audit and cannot silently
skip configured baselines or required previews. Without injected services,
legacy fallback callbacks remain technical reopen checks, not rendered QA.

`pdf_reproducibility` injects the same comparator used by the CLI fallback:
PDF page count, geometry, extracted text, and rendered page content at 150 DPI
must match. PDF container bytes and metadata comments need not match. This
checks the current renderer, not equivalence across renderer versions or every
possible zoom level. DOCX and HTML retain byte-level reproducibility checks.

- **HTML accessibility:** declared nonempty `html[lang]`, a visible nonempty
  `h1`, basic heading-level progression, main/header landmarks (or equivalent
  roles), and image `alt` attributes. Empty alt is allowed for decorative images.
  Hidden/template content does not satisfy these checks. This is not WCAG
  conformance, contrast, keyboard, or assistive-technology testing.
- **PDF accessibility:** retains technical reopen/page checks and reports
  `accessibility.pdf.untagged` if the catalog does not declare tagged structure.
  Declared tags or an unavailable tag probe yield `accessibility.pdf.tags_unverified`:
  semantic tags, reading order, and text alternatives are not validated.
- **Visual inspection:** PDFium reuses the existing page renderer and checks
  blank pages, expected dimensions, decodability of top-level images, and
  text/image bounds outside the crop box. Arbitrary clipping paths, nested-form
  transforms, overlap, and intentional bleed are not inferred. Bounds extending
  outside the crop box are warnings, not proof of accidental clipping.
  HTML checks static body content, embedded/local images, and declared pixel
  dimensions exceeding ancestor dimensions. Such declared overflow/clipping is
  a warning requiring browser confirmation, not computed-layout evidence.
- **Capability boundary:** no browser is launched or installed. HTML always
  reports `render.layout.unavailable`; requested HTML previews additionally
  report `render.previews.unavailable`. SVG XML can be inspected but its rendered
  appearance remains unverified. External image URLs are not fetched.

The service uses `visual_qa.allow_blank_pages` (default false),
`visual_qa.require_previews` (default false), and optional
`visual_qa.expected_page_size` (PDF points; two positive finite numbers).
With `paths.output_qa_dir`, CLI previews go under `<document-id>.<format>/previews/`
and are named `<document-id>.<format>-pNN.png`, independent of build/run tokens.
Direct adapter calls default to the artifact stem; callers may supply the stable
`RenderProfile.preview_stem`. Existing token-named baselines require an explicit
baseline update; verification never migrates them automatically. Without an
output directory, PDF pages are still rasterized and inspected in memory.
Draft permits warnings; strict/release and matching `warning_codes` promote
them to errors. Missing artifacts and corrupt images remain errors in draft.
Accessibility and visual findings are gated separately.

HTML rendering also embeds deterministic CSS from `format.visual_theme` and
generated cover variants. Colors, typography, spacing, cover accents and variant
layout are explicit; an absent theme and absent generated cover preserve the
legacy HTML bytes. This styling is not a visual-accessibility certification.

## Degradation rules

Draft mode may preserve permitted optional gaps as warnings and never publishes. Strict and release promote warnings or required capability gaps to errors. `unsupported` is always visible in stage results; it is not silently converted into a completed implementation. Missing optional previews or tools must remain visible in reports.

## CI evidence

The repository workflow runs lint, type checks, tests, architecture invariants, and a full optional-toolchain job. The toolchain job is important because the normal check job intentionally exercises degradation without every optional tool. See [ci-v2.md](ci-v2.md) for the exact workflow.

## Visual baseline snapshots

QA compares rendered previews against `visual_qa.baseline_dir` when configured.
Updating a baseline is an explicit authoring operation and never happens during
`build` or `verify`:

```text
docs document baseline <preview-dir> --destination <baseline-dir>
docs document baseline <preview-dir> --destination <baseline-dir> --update
```

The command validates every PNG, stages the complete set in a scratch directory,
and publishes the directory atomically. An existing baseline is preserved unless
`--update` is supplied; incomplete or corrupt previews are never published.

