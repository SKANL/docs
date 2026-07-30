# Delta for Template Provisioning

## ADDED Requirements

### Requirement: Template-Driven Review-Rule Configuration

Each template MUST declare its own review-rule data — citation style,
contested-stack terms, subjective-word list, forbidden-word list, and format
params — in its config, instead of relying on hardcoded values in
`rules.py`/`source_role.py`. `citation_style` MUST accept `apa7` or `none`,
with only `apa7` implemented (a seam for future styles).

#### Scenario: Estadia declares current rule values
- GIVEN the estadia template's config
- WHEN review runs against an estadia document
- THEN the review outcome is byte-identical to pre-refactor behavior

#### Scenario: A different template's config changes review outcomes
- GIVEN a second template with a different contested-stack-term list and
  `citation_style: none`
- WHEN review runs against a document using that template
- THEN the review outcome reflects that template's rule config, with no code
  change required

#### Scenario: `citation_style` accepts the declared enum
- GIVEN a template config with `citation_style: apa7` or `citation_style: none`
- WHEN the template is loaded
- THEN it is accepted; any other value is rejected with a clear error

### Requirement: Second Built-In Non-APA Template

The system MUST ship a second built-in template (English, non-APA,
structurally different from estadia) as package data, with its own
review-rule config, plus an end-to-end acceptance test that builds a
document with it.

#### Scenario: Second template listed and usable
- GIVEN the package-shipped templates
- WHEN `template list --available` runs
- THEN both the estadia template and the new non-APA template are listed
  and instantiable via `template use`

#### Scenario: Acceptance test builds and reviews the second template
- GIVEN a document created from the second template with its distinct rule
  config
- WHEN the full pipeline runs (ingest → author → review → assemble)
- THEN it completes successfully and review reflects the second template's
  rules, not estadia's
