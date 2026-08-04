# Delta for Document Render

## ADDED Requirements

### Requirement: HTML Prefers Sibling SVG for a Bound Figure

When resolving a bound figure (`[[figure:label]]`) for HTML output, if the
resolved figure's catalog PNG has a sibling `.svg` file (same stem, same
`assets_dir/figures/` directory — as produced by document-visuals'
generate-visuals stage), the HTML renderer MUST embed the SVG instead of the
PNG, so generated diagrams stay crisp/vector in HTML. The docx renderer
MUST continue to embed the catalog PNG unconditionally (SVG cannot be
reliably embedded in docx via pandoc — jgm/pandoc#9195). This preference is
a format-specific substitution at the embed step only; it MUST NOT alter the
figure's registered dimensions, caption, or assigned number.

#### Scenario: Bound figure with a sibling SVG embeds the SVG in HTML

- GIVEN a bound figure whose catalog PNG has a sibling `.svg` file under
  `assets_dir/figures/`
- WHEN the document is built to HTML
- THEN the assembled HTML embeds the SVG, not the PNG

#### Scenario: The same bound figure still embeds the PNG in docx

- GIVEN the same bound figure with a sibling `.svg` file
- WHEN the document is built to docx
- THEN the assembled docx embeds the catalog PNG, unaffected by the sibling
  SVG's presence

#### Scenario: A bound figure with no sibling SVG behaves as before

- GIVEN a bound figure with only a catalog PNG and no sibling `.svg` file
  (e.g. a plain ingested photo)
- WHEN the document is built to HTML or docx
- THEN both formats embed the PNG, exactly as before this requirement

#### Scenario: Numbering and cross-references are unaffected by the format swap

- GIVEN a bound figure with a sibling SVG, referenced by a "Ver {ref}"
  cross-reference in the same section
- WHEN the document is built to HTML
- THEN the figure's assigned number and the cross-reference resolve
  identically to the docx build, only the embedded image format differs
