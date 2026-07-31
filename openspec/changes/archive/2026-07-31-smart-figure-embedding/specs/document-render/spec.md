# Delta for Document Render

## ADDED Requirements

### Requirement: Bound Figure Label Resolves to an Embedded Image

A symbolic figure label (`[[figure:label]]`) bound to a catalog figure MUST
resolve, at build/assemble time, to an EMBEDDED image in the assembled
output -- not merely to a text caption/number. Embedding MUST be achieved by
emitting Markdown image syntax (`![caption](path){width=...}`) at the
label-resolution hook so the existing pandoc-backed render path embeds the
image natively; no new manual image-insertion mechanism is required. An
UNbound label (no catalog figure bound to it) MUST remain text-only, exactly
as it behaves today, so existing documents that only use text
numbering/cross-references are unaffected.

#### Scenario: Bound label embeds the image

- GIVEN a symbolic figure label bound to a figure present in the figure
  catalog under `assets_dir/figures/`
- WHEN the document is built
- THEN the assembled output contains the embedded image at the label's
  resolved position, alongside its resolved caption and number

#### Scenario: Unbound label stays text-only

- GIVEN a symbolic figure label with no catalog figure bound to it
- WHEN the document is built
- THEN the label resolves to text (caption/number) only, with no image
  embedded, matching prior behavior

#### Scenario: Embedding does not alter numbering/cross-reference resolution

- GIVEN a section containing both a bound figure label and a "Ver {ref}"
  cross-reference to it
- WHEN the document is built
- THEN the figure number and cross-reference resolve exactly as they did
  before this requirement, in addition to the image now being embedded

### Requirement: Graceful Degradation on Missing or Corrupt Bound Image

If a bound figure label's underlying image file is missing or unreadable at
build time, the system MUST degrade to caption-only rendering for that
figure (numbering and cross-references still resolve) and MUST WARN naming
the affected label and file, rather than crashing the assemble stage.

#### Scenario: Missing image file degrades gracefully

- GIVEN a symbolic figure label bound to a catalog entry whose image file
  has been deleted from `assets_dir/figures/` since ingest
- WHEN the document is built
- THEN the build completes, the figure's caption and number still resolve,
  no image is embedded for that figure, and the build output includes a
  WARNING naming the missing file

#### Scenario: Corrupt image file degrades gracefully

- GIVEN a symbolic figure label bound to a catalog entry whose image file is
  present but unreadable/corrupt
- WHEN the document is built
- THEN the build completes without crashing, the figure's caption and
  number still resolve, no image is embedded for that figure, and the build
  output includes a WARNING naming the affected label and file

#### Scenario: One degraded figure does not affect other figures

- GIVEN a document with multiple bound figure labels, one of which has a
  missing image
- WHEN the document is built
- THEN every other bound figure embeds normally, and only the affected
  figure degrades to caption-only

### Requirement: Embedded-Image Build Determinism

The assembled output produced by the embedded-image build path MUST be
byte-identical across independent runs given unchanged section Markdown,
figure catalog, and configuration -- matching the existing determinism
guarantee for non-embedded builds.

#### Scenario: Embedded build is byte-identical across runs

- GIVEN unchanged section Markdown, an unchanged figure catalog, and
  unchanged configuration, with at least one bound figure label
- WHEN the document is built twice independently
- THEN the two output files are byte-identical
