# docs — a deterministic document-creation harness

Turn source material and a document template into a finished `.docx`, HTML or
PDF, where **every mechanical step is done by the harness and exactly one step
is left to a human or an AI agent**: writing the prose.

```
inbox/  →  ingest  →  context  →  prep  →  ✍ author  →  review  →  assemble  →  verify
                                            ▲
                                            └── the only cognitive slot
```

## The one idea

Most document tooling asks a model to produce the whole document and then
hopes the result is right. This inverts that. The harness owns figure and
table numbering, cross-reference resolution, section ordering, cover and TOC
assembly, `.docx` structure, deterministic zip output and every review
heuristic. It never guesses prose. The author — human or agent — writes the
body of each section's `.md` file, and nothing else.

That boundary is what makes the second property possible:

> **`.md` → `.docx`/HTML is a byte-identical pure function.** Same sections,
> same template, same config → the same bytes, on any machine, every time. If
> an unchanged source produces different output, that is a harness bug, not
> environmental noise.

PDF is an explicitly excepted derived artifact: it goes through LibreOffice,
whose rendering varies by version, and is never held to byte identity.

## Native contracts and QA

The CLI is self-contained: it does **not** require the Documents, PDF, or Template Creator plugins at runtime. Plugins may assist a user, but artifact generation, provenance, verification, and publication remain native harness responsibilities.

- **Contracts and provenance:** transforms declare expected artifacts; outputs and section edits retain evidence, hashes, authorship, diffs, and append-only history.
- **Safe publication:** transforms build in scratch, validate declared outputs, then publish; failed publication restores the previous output and cleans temporary files.
- **Verification:** editorial review checks prose, structural verification checks document mechanics and template requirements, and visual verification checks rendered pages.
- **Degradation:** draft mode reports permitted missing tools/evidence as warnings or skips; strict mode requires complete evidence and gates on applicable errors.
- **Template fidelity:** templates may opt into `template_contract` for geometry, styles, components, editable slots, assets, fidelity checks, and allowed degradations.

Assembly writes `qa-report.md` plus available render previews below the configured QA output directory (normally `output/qa/<artifact-stem>/previews/`). Open the report and page images together; `docs doctor` explains unavailable optional tools. Extend the system by implementing and registering a renderer behind its domain port with deterministic/degradation tests, or by scaffolding and validating a data-only template with `docs template init <id>` and `docs template validate <id>`.

## Quick start

```bash
uv sync
uv run docs doc init                 # bootstrap a workspace
uv run docs doc new mi-informe       # create a document
uv run docs pipeline ingest          # convert whatever is in inbox/
uv run docs pipeline prep            # rules, evidence, section scaffolds
#   ...author the section bodies under sections/NNN-<id>.md...
uv run docs review-section intro --json   # iterate until "passed": true
uv run docs pipeline assemble        # build the output
```

`docs guide` prints the full agent contract — the end-to-end workflow,
conventions, and the exact boundary between what the harness does and what you
write. `docs explain <code>` explains any finding the review loop reports.

## What a document type is

A template is one JSON file. It declares the sections, what each section's
contract requires, the context topics to elicit, the citation policy, the page
geometry and the strict-mode policy. Adding a new kind of document means
writing that file — never touching Python.

```bash
uv run docs template init informe-tecnico   # documented skeleton
uv run docs template validate informe-tecnico
```

Three templates ship built in: `documento-generico`, `technical-report-srs`
and `reporte-estadia-tic`.

## Architecture

Hexagonal, and enforced rather than asserted:

```
cli/ ──▶ application/ ──▶ domain/          infrastructure/ ──implements──▶ domain/ports/
```

- `domain/` — pure logic and `typing.Protocol` ports. No I/O.
- `application/` — services that depend only on ports.
- `infrastructure/` — adapters: python-docx, pandoc, LibreOffice, pdfium2,
  matplotlib, mermaid-cli, resvg.
- `cli/` — Typer commands; `cli/_shared.py` is the only composition root.

`tests/architecture/` turns the rules into checks: the layering rule is
verified against the GitNexus import graph, every `.docx` writer is proven to
route through the deterministic-zip normalizer, and every capability spec is
proven to name the code that implements it.

## Requirements

Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/). Everything else is
optional and degrades to a warning rather than a failure:

| Tool | Needed for | Without it |
|---|---|---|
| `pandoc` | markdown → docx/HTML | those formats are skipped |
| LibreOffice | PDF output, visual QA | PDF and visual QA are skipped |
| Java | some PDF ingest paths | those sources are skipped |
| `mmdc` (mermaid-cli) | mermaid diagrams | that visual is skipped |
| `resvg` | SVG → PNG | that figure is skipped |

`docs doctor` reports which of them it can find.

## Development

```bash
uv run pytest              # 1563 tests
uv run ruff check .
uv run mypy
```

CI runs all three on every push and pull request, with a coverage floor.

- `AGENTS.md` — the agent contract (also `docs guide`)
- `CLAUDE.md` — conventions, determinism gotchas, knowledge-graph routing
- `openspec/specs/` — the 12 capability contracts
