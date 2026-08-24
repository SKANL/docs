# Proposal: Typed Config Envelope

## Intent

A typo in a template's configuration is accepted, silently ignored, and
changes the document that gets produced. `template validate` already catches
this for the MODELLED half of a template (`sections`, `section_contracts`,
`context_schema`, `apa7`, `strict_policy`) via near-miss key detection. The
config envelope — the ten blocks no model declares — has no such net, and it
is the half that decides page geometry, output naming and normative rules.

## Evidence

Measured on `main` at the time of writing:

```
126 config[...] / config.get(...) accesses across 23 files
 74 of them into ["paths"]
```

`Template` carries ten top-level blocks that no model declares and
`resolve_context` merges and hands to every service as `dict[str, Any]`:
`format`, `paths`, `normative`, `privacy`, `output`, `preliminaries`,
`cross_consistency`, `advisor_overrides`, `documents_tools`, `ledger_seed`.

The concrete failure, in `apply_non_cover_section_layout`:

```python
margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
value = margins.get(key)
if isinstance(value, (int, float)):
    setattr(section, attr, Cm(float(value)))
```

Write `to` instead of `top` and the margin is never applied. The template
validates. The document builds. Nothing reports anything. The printed page is
simply wrong — and page geometry is exactly the kind of requirement an
institution rejects a document over.

This is the same defect class as `required_contents`, which was fixed in the
modelled half. The unmodelled half is the larger one.

## Scope

### In Scope

- A declared vocabulary of the config keys the harness actually reads.
- Near-miss detection over the config envelope in `template validate`,
  reusing the existing `_check_near_miss_keys` machinery and the existing
  `template.unknown_key` code — no second mechanism, no second issue code.
- A mechanical guard proving the declared vocabulary matches the keys the
  source really reads, so it cannot drift into fiction.

### Out of Scope

- Typing the ten blocks as Pydantic models. See `design.md` Decision 1: it
  would change the signature of every one of the 23 consuming files for the
  same user-visible outcome — one warning naming the mistyped key.
- Rejecting unknown config keys. The envelope is open by contract:
  `resolve_context` merges template, document and computed values, and a
  workspace may legitimately carry keys this harness version does not read.
- `paths` values that are computed rather than declared. `_computed_paths`
  owns those; a template override of a computed key is a separate concern.

## Approach

Declare the vocabulary as DATA, derive the guard from the CODE.

`domain/config_vocabulary.py` names the known keys per block.
`tests/architecture/test_config_vocabulary.py` AST-scans `src/docs` for every
`config[...]`/`config.get(...)` access and fails if the declaration and the
code disagree in either direction. One declaration, mechanically kept honest
— rather than a second source of truth that rots.

## Risk

Low. Additive: one new pure module, one new check inside an existing
validation function, one new architecture test. No consumer signature
changes, no runtime behaviour change outside `template validate`'s output.

The real risk is a NOISY check — flagging a deliberate extension key as a
typo. Mitigated the same way the modelled half is: only a key close enough to
a real one (difflib ratio ≥ 0.8) is reported, `$`/`_`-prefixed keys are never
reported, and the finding is a warning rather than a rejection.
