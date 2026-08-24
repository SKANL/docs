# Template Provisioning Specification

## Purpose

Ship usable document templates with the harness itself, so a document can be started without a project-specific fixture already living in the consuming repo.

Implemented by `resolve_normative_settings` in `normative`, which extracts every review-rule input from template data, plus the `Apa7Config` and `StrictPolicy` models that type those blocks. `template_use` provisions a builtin template into a workspace.

## Requirements

### Requirement: Built-In Templates as Package Data

The system MUST ship at least one built-in template as package data (installed with the harness), independent of any consuming repository's `tests/fixtures/` or similar local paths.

#### Scenario: Built-in template available after install

- GIVEN the `docs` package is installed with no project-local template fixtures present
- WHEN a built-in template is requested
- THEN it is found and usable without any extra file present in the workspace

### Requirement: `template list --available` Command

The system MUST provide a command listing all built-in templates shipped with the package, distinct from templates already copied into the active workspace.

#### Scenario: List built-in templates

- GIVEN one or more built-in templates ship with the package
- WHEN `template list --available` runs
- THEN it prints each built-in template's identifier
- AND does not require a workspace to already contain a copy

### Requirement: `template use <builtin>` Command

The system MUST provide a command that copies a named built-in template into the active workspace, making it usable by the standard template machinery.

#### Scenario: Instantiate a built-in template

- GIVEN a built-in template identifier from `template list --available`
- WHEN `template use <builtin>` runs
- THEN the template is copied into the workspace's templates directory
- AND is subsequently usable like any workspace-local template

#### Scenario: Unknown built-in identifier

- GIVEN an identifier not present in the built-in template set
- WHEN `template use <identifier>` runs
- THEN the system raises a clear error naming the unknown identifier
- AND does not partially copy files

### Requirement: Template-Driven Review-Rule Configuration

Each template MUST declare its own review-rule data — citation style, contested-stack terms, subjective-word list, forbidden-word list, and format params — in its config, instead of relying on hardcoded values in `rules.py`/`source_role.py`. `citation_style` MUST accept `apa7` or `none`, with only `apa7` implemented (a seam for future styles).

#### Scenario: Estadia declares current rule values

- GIVEN the estadia template's config
- WHEN review runs against an estadia document
- THEN the review outcome is byte-identical to pre-refactor behavior

#### Scenario: A different template's config changes review outcomes

- GIVEN a second template with a different contested-stack-term list and `citation_style: none`
- WHEN review runs against a document using that template
- THEN the review outcome reflects that template's rule config, with no code change required

#### Scenario: `citation_style` accepts the declared enum

- GIVEN a template config with `citation_style: apa7` or `citation_style: none`
- WHEN the template is loaded
- THEN it is accepted; any other value is rejected with a clear error

### Requirement: Second Built-In Non-APA Template

The system MUST ship a second built-in template (English, non-APA, structurally different from estadia) as package data, with its own review-rule config, plus an end-to-end acceptance test that builds a document with it.

#### Scenario: Second template listed and usable

- GIVEN the package-shipped templates
- WHEN `template list --available` runs
- THEN both the estadia template and the new non-APA template are listed and instantiable via `template use`

#### Scenario: Acceptance test builds and reviews the second template

- GIVEN a document created from the second template with its distinct rule config
- WHEN the full pipeline runs (ingest → author → review → assemble)
- THEN it completes successfully and review reflects the second template's rules, not estadia's
