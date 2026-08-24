# Tasks: Typed Config Envelope

Delivery strategy: single PR. Forecast is well under 400 authored lines (one
pure module, one function in an existing validator, one architecture test),
so the workload guard does not require chaining.

Strict TDD on every task: the failing test is written and RUN (red) before
any implementation line. No task is done until its tests are green and no
unrelated test regressed.

Hexagonal boundaries: `config_vocabulary` is pure domain data — no imports
from `application/` or `infrastructure/`, no I/O.

## 1. Prove the gap before closing it

- [x] 1.1 Write a failing test showing a mistyped config key is accepted in
      silence today: a template with `format.page_margins_cm.non_cover.to`
      passes `validate_template` with zero findings.
- [x] 1.2 Confirm the same typo really does drop the margin, so the test is
      pinning a consequence and not a preference.

## 2. Declare the vocabulary

- [x] 2.1 Write the architecture test FIRST: AST-scan `src/docs` for
      `config["x"]` and `config.get("x")` chains, and assert the collected
      keys equal `CONFIG_VOCABULARY` in both directions.
- [x] 2.2 Add the scan's own vacuity guard: assert it found a non-trivial
      number of accesses, so a walk that stopped matching cannot pass by
      finding nothing.
- [x] 2.3 Create `domain/config_vocabulary.py` with the keys the scan
      reports, nested to the depth the code reads. Pure data.

## 3. Wire the check

- [x] 3.1 Extend `_check_near_miss_keys` to walk the config envelope against
      `CONFIG_VOCABULARY`, reusing `_near_miss_keys`' cutoff, `$`/`_` skip
      and `template.unknown_key` code. No second mechanism.
- [x] 3.2 Green 1.1: the mistyped margin key is now reported, naming `top`.
- [x] 3.3 Test that an unrecognised top-level block is NOT reported — the
      envelope is open and a forward-declared block is not a typo.
- [x] 3.4 Test that `$comment`/`_`-prefixed keys are never reported at any
      envelope nesting level.
- [x] 3.5 Test all three builtin templates still validate with zero near
      misses.

## 4. Close the loop

- [x] 4.1 Confirm `template.unknown_key`'s catalog entry still describes both
      cases accurately; extend its wording only if it does not.
- [x] 4.2 Full suite, ruff, mypy green.
- [x] 4.3 Merge the delta specs into `openspec/specs/` and archive.

## Verification

- Focused: `uv run pytest tests/unit/domain/test_template_validation.py tests/architecture/test_config_vocabulary.py -q`
- Runtime harness: `uv run python -m docs.cli.main template validate <fixture>`
  against a template carrying the mistyped margin key — the finding must
  reach the CLI surface, not just the domain function.
- Rollback boundary: `domain/config_vocabulary.py`,
  `tests/architecture/test_config_vocabulary.py`, and the
  `_check_config_envelope` call inside `validate_template`. Removing those
  three restores previous behaviour with nothing else touched.
