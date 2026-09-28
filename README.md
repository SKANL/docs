<div align="center">

# docs

### A deterministic document-creation harness

Turn source material and a declarative template into reviewable **DOCX**, **HTML**, and **PDF** artifacts—without delegating document mechanics to a language model.

`Python 3.11+` · `uv` · `DOCX / HTML / PDF` · `Deterministic by design`

</div>

---

## The promise

Most document tooling asks a model to generate everything and then hopes the result is correct. **docs** draws a harder boundary:

| You write | The harness guarantees |
| --- | --- |
| The section prose, arguments, and evidence | Structure, numbering, references, rendering, review, QA, provenance, and safe publication |

That boundary leaves one deliberate cognitive slot—writing the document—while making the rest observable and repeatable.

> [!IMPORTANT]
> DOCX and HTML builds are byte-deterministic for unchanged inputs. PDF is a derived artifact rendered through LibreOffice, so its bytes may vary by renderer version.

```text
inbox/ → ingest → context → prepare → write prose → review → build → verify
                                        ▲
                                        └── the only cognitive slot
```

## Start here

**Prerequisites:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# Create a document workspace and an active document.
uv run docs doc init
uv run docs doc new my-report

# Add source material under the active document's inbox/, then prepare it.
uv run docs document ingest
uv run docs document prepare

# Write the bodies in sections/NNN-<id>.md, then review and build.
uv run docs review-section intro --json
uv run docs document build --format docx --format html --format pdf --json
```

Run `uv run docs doctor` at any point to see which optional local tools are available and what degrades when one is absent.

## What you get

| Capability | What it does |
| --- | --- |
| **Source intake** | Converts and classifies inbox material without injecting it into authored prose. |
| **Declarative templates** | Define sections, context, policies, geometry, and review requirements as data. |
| **Deterministic rendering** | Builds DOCX and HTML reproducibly; treats PDF as an explicitly derived format. |
| **Layered QA** | Separates editorial, structural, accessibility, visual, and reproducibility checks. |
| **Evidence and publication** | Records manifests and provenance before atomically publishing verified artifacts. |
| **Optional capabilities** | Uses Pandoc, LibreOffice, Mermaid, resvg, and browser QA when available; reports honest degradation when they are not. |

## The workflow at a glance

```text
Template + context + sources + authored Markdown
                    │
                    ▼
          contract-driven pipeline
                    │
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
   DOCX           HTML           PDF*
     │              │              │
     └──── QA, manifests, provenance ────┘
                    │
                    ▼
     verified artifacts and release package

* PDF is rendered through LibreOffice and is not byte-deterministic.
```

### Create and author a document

1. Run `docs doc init` once in a workspace.
2. Choose or create a template, then run `docs doc new <id>`.
3. Place raw material in `<document>/inbox/` and run `docs document ingest`.
4. Run `docs document prepare` to normalize sources and scaffold sections.
5. Edit only the Markdown body below each section's managed front matter.
6. Run `docs stamp-section <id> --by <author>` after authoring.
7. Iterate on `docs review-section <id> --json`, then build and verify.

> [!TIP]
> `build-section` is scaffolding, not an authoring command. Once prose exists, use `stamp-section`; it preserves the body and refreshes provenance metadata.

## Output and verification

The `document` command group is the public pipeline interface:

```bash
uv run docs document build --format docx --format html --format pdf --json
uv run docs document verify --format docx --format html --format pdf --json
uv run docs document inspect <artifact> --json
uv run docs document diff <before> <after> --json
```

When the selected pipeline and policy permit publication, verified build artifacts are written under the active document root's `output/current/`. Release packages belong under `output/release/`; direct package and publish commands require explicit, cwd-relative source and destination paths.

## Templates and formats

Templates are JSON contracts, not Python extensions. A template can declare section structure, required context, citation rules, page geometry, and strict policy without changing the harness.

```bash
uv run docs template list --available
uv run docs template init technical-report
uv run docs template validate technical-report
```

Built-in templates: `documento-generico`, `technical-report-srs`, and `reporte-estadia-tic`.

## Architecture in one picture

```text
CLI / API / workers
        │
        ▼
application services
        │
        ▼
domain models + ports  ◀── infrastructure adapters
```

The runtime center is a contract-validated pipeline DAG. The composition root connects domain ports to renderers, repositories, QA adapters, locks, and publication services.

## Optional local tools

| Tool | Enables | Without it |
| --- | --- | --- |
| Pandoc | Markdown → DOCX / HTML | Those formats are skipped with evidence. |
| LibreOffice | PDF output and visual QA | PDF and visual review are skipped. |
| Java | Some PDF ingestion paths | Affected source files are skipped. |
| Mermaid CLI + resvg | Generated Mermaid figures | The affected visual is skipped. |
| Playwright + browser | Browser-level HTML QA | Static HTML checks still run. |

## For contributors

```bash
uv run pytest
uv run ruff check src tests
uv run mypy src tools
```

The suite includes unit, integration, toolchain, and architecture checks. The architecture tests enforce dependency direction, deterministic document writing, and declared capability evidence.

## Go deeper

| Need | Read |
| --- | --- |
| End-to-end authoring contract | [AGENTS.md](AGENTS.md) or `docs guide` |
| Runtime boundaries and stages | [Architecture](docs/architecture.md) · [Pipeline](docs/pipeline.md) |
| Template authoring | [Templates](docs/templates.md) · [Covers](docs/covers.md) |
| Verification and evidence | [QA](docs/qa.md) · [Provenance](docs/provenance.md) |
| Service operation | [Deployment](docs/deployment.md) · [API transport](docs/api-transport.md) |
| Platform integrations | [Plugins](docs/plugins.md) · [Tauri desktop](docs/desktop-tauri.md) |

---

<div align="center">

**Write the document. Let the harness prove the mechanics.**

</div>