# Delta for Document Template

## MODIFIED Requirements

### Requirement: Near-Miss Key Detection

Template models accept unknown keys by design (`$comment` self-documentation
siblings, and untyped `SectionContract` passthrough that reaches the rendered
context pack). `template validate` MUST therefore report an unknown key that
closely resembles a real field, naming the field it likely meant, so a typo
cannot silently disable the rule the author intended to declare. The report
MUST be a warning, never a rejection: an unknown key that resembles nothing
is a deliberate extension and MUST pass unremarked.

This MUST cover the CONFIG ENVELOPE as well as the modelled blocks — the
top-level `format`, `paths`, `normative`, `privacy`, `output`,
`preliminaries`, `cross_consistency`, `advisor_overrides`, `documents_tools`
and `ledger_seed` blocks that no model declares and `resolve_context` consumes
raw — including their nested keys to the depth the harness actually reads.
Both cases MUST use the same `template.unknown_key` code: one concept, one
diagnostic.

#### Scenario: A mistyped contract key is named

- GIVEN a section contract declaring `required_contents` instead of `required_content`
- WHEN `template validate` runs
- THEN it reports `template.unknown_key` naming both the typo and the real field
- AND the severity is warning, not error

#### Scenario: A mistyped config key is named

- GIVEN a template declaring `format.page_margins_cm.non_cover.to` instead of `top`
- WHEN `template validate` runs
- THEN it reports `template.unknown_key` naming both the typo and `top`
- AND the margin it would have set is identified as not applied

#### Scenario: A deliberate passthrough key is left alone

- GIVEN a section contract carrying an untyped key resembling no real field
- WHEN `template validate` runs
- THEN no `template.unknown_key` issue is reported
- AND the key still survives into the rendered context pack

#### Scenario: An unrecognised config block is left alone

- GIVEN a template declaring a top-level block this harness version does not read
- WHEN `template validate` runs
- THEN no `template.unknown_key` issue is reported, because the envelope is
  open by contract and a forward-declared block is not a typo

#### Scenario: Documentation siblings are never flagged

- GIVEN a template using `$comment` or `_`-prefixed keys at any nesting level
- WHEN `template validate` runs
- THEN none of them is reported as a near miss
