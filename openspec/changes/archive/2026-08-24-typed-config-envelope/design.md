# Design: Typed Config Envelope

## Decision 1 — Detect typos, do not type the world

**Rejected: model the ten blocks as Pydantic classes.**

It is the obvious answer and it is the wrong trade. The config reaching a
service is not a template block: `Deps.resolve_context` deep-merges the
template, the document's overrides and `_computed_paths` into one
`dict[str, Any]`, and 23 files read it with 126 subscript accesses. Typing
the envelope means either

- changing every consumer to take a model (a signature change across the
  application and infrastructure layers, for a merge product that is
  deliberately open), or
- validating into a model and then throwing it away to keep passing the dict
  — a model that exists only to be discarded.

The second is what typing would actually amount to here, since the merge and
the `structure` splicing both operate on the raw dict. And the user-visible
outcome of either is identical to the cheap option: **one warning naming the
mistyped key.**

**Chosen: extend the near-miss net that already exists.** The modelled half
of a template is protected by `_check_near_miss_keys`, which reports an
unknown key that is one edit from a real field. The envelope needs the same
thing; the only missing ingredient is a list of real field names, because
there is no model to read them from.

## Decision 2 — Declare the vocabulary, derive the guard

A hand-written list of known config keys is a second source of truth, and a
second source of truth rots: a new key gets read in `pipeline.py`, nobody
updates the list, and the net stops covering it — silently, which is the
exact failure mode this change exists to remove.

So the list is declared once (`domain/config_vocabulary.py`, pure data, no
I/O) and a test derives the truth from the code: an AST scan of `src/docs`
collecting every `config["x"]` and `config.get("x")` key, compared against the
declaration in **both** directions.

- A key the code reads but the vocabulary omits → the net has a hole → fail.
- A key the vocabulary declares but nothing reads → the vocabulary is
  documenting something that no longer exists → fail.

This is the same bidirectional shape as the issue-code catalog guard, and for
the same reason: a catalog that can only be too small is a catalog that
quietly becomes useless.

## Decision 3 — Warning, never rejection

The envelope is open by contract. `resolve_context` merges three sources via `_deep_merge`, and
a workspace may carry keys a given harness version does not read — an older
document, a newer template, a forward-declared block. Rejecting an unknown
key would break real workspaces to catch a typo.

A near-miss warning costs nothing when wrong and names the exact mistake when
right. It reuses `template.unknown_key`: same code, same catalog entry, same
severity. A second issue code for "the same mistake, one level up" would be
two things to learn for one concept.

## Decision 4 — Nested keys, one level of nesting

The scan resolves chained access (`config["format"]["page_margins_cm"]`) so
the vocabulary is a tree, not a flat set. It stops at the depth the code
actually reads; going deeper would invent structure nobody references.

`paths` is checked like any other block, but the vocabulary marks which of
its keys `_computed_paths` supplies. A template overriding a computed path is
legitimate; a template MIS-SPELLING one silently loses the override, which is
precisely the case worth reporting.

## Decision 5 — Where the check runs

Inside `validate_template`, next to `_check_near_miss_keys`. Not a new
command and not a pipeline stage: `template validate` is already the place a
user asks "is my template right?", and the answer belongs there rather than
in a stage that runs much later, after the wrong margin has already been
applied.

## Consequences

- One new pure domain module and one new architecture test.
- `template validate` gains findings it did not previously emit. Existing
  templates are checked: all three builtins pass with zero near misses
  (verified before implementation).
- The vocabulary becomes a small maintenance obligation — but a MECHANICAL
  one: forgetting it fails the build rather than degrading the net.
