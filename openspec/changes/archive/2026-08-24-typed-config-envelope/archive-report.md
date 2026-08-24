# Archive Report: Typed Config Envelope

## Outcome

`template validate` now covers the config envelope — the ten top-level blocks
no model declares — with the same near-miss detection that already protected
the modelled half. A mistyped key that silently changes the produced document
is named, along with the key it meant.

## Verification

- Focused: `tests/unit/domain/test_template_validation.py` (21 passed),
  `tests/architecture/test_config_vocabulary.py` (5 passed).
- Runtime harness: `docs template validate` against a template carrying
  `format.page_margins_cm.non_cover.to`. Exit 1, and the finding reaches the
  CLI surface verbatim:

      WARNING: Clave de configuración desconocida
      `format.page_margins_cm.non_cover.to`, muy parecida a `top`.

- Full suite: 1578 passed, 7 skipped. ruff and mypy clean.

## What it found on its first run

`paths.manual_pdf` in the shipped `reporte-estadia-tic` template. Nothing
under `src/` reads it — a leftover from the legacy harness that the migration
carried across as a declaration nobody consumes. Marked `_manual_pdf` rather
than deleted: the convention already exists for "this is deliberately not a
field", and the location of the guide PDF is worth keeping as a note.

The spec-anchor guard also caught this change's own writing: the delta named
`resolve_config`, a function that never existed (the merge is
`resolve_context` + `_deep_merge` + `_computed_paths`). Corrected in every
artifact. A contract that names a phantom symbol is exactly what that guard
was added for, and it fired on the author rather than on someone else later.

## Deliberately not done

Typing the ten blocks as Pydantic models — see `design.md` Decision 1. It
would change the signature of 23 consuming files to produce the same single
warning, over a merge product that is open by contract.

## Rollback boundary

`domain/config_vocabulary.py`, `tests/architecture/test_config_vocabulary.py`,
and the `_check_config_envelope` / `_near_miss_against` pair in
`template_validation.py`. Removing those restores previous behaviour with
nothing else touched.
