# Delta for Document Render

## ADDED Requirements

### Requirement: Deterministic HTML Renderer

The system MUST implement `DocumentRendererPort` for the `html` format
(pandoc-backed), registered in the format registry, producing byte-identical
output for unchanged Markdown sources and configuration.

#### Scenario: HTML renderer registered
- GIVEN the format registry
- WHEN resolving a renderer for `html`
- THEN the pandoc-backed HTML adapter is returned

#### Scenario: HTML output is byte-deterministic
- GIVEN unchanged section Markdown and configuration
- WHEN the HTML document is built twice
- THEN the two HTML files are byte-identical

### Requirement: Best-Effort PDF Renderer With Graceful Degradation

The system MUST implement `DocumentRendererPort` for the `pdf` format
(soffice/pandoc-backed). PDF output MUST NOT be required byte-deterministic.
When the PDF toolchain is unavailable, the system MUST WARN and skip PDF
generation rather than hard-failing the build.

#### Scenario: PDF renders when toolchain present
- GIVEN `soffice` or a PDF-capable `pandoc` path is available
- WHEN a build requests `pdf` output
- THEN a PDF artifact is produced via the format registry

#### Scenario: PDF toolchain absent warns and skips
- GIVEN neither `soffice` nor a PDF-capable `pandoc` path is available
- WHEN a build requests `pdf` output
- THEN the system WARNs naming the missing toolchain, skips the PDF
  artifact, and other requested formats still succeed

#### Scenario: PDF output is not byte-deterministic
- GIVEN unchanged section Markdown and configuration
- WHEN the PDF document is built twice
- THEN the two PDF files may legitimately differ without being treated as a
  determinism failure
