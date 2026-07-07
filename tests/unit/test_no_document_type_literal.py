# tests/unit/test_no_document_type_literal.py
"""Structural guard (house precedent: `test_module_source_has_no_tesina_literal`)
enforcing the universal-schema-harness contract: no document-type-specific
literal (a fixed section id, a fixed policy value, or a Spanish-thesis
writing-pattern lexicon entry) may live in `domain/rules.py` or
`domain/normative.py`. All such policy MUST be declared as template data.

This test is EXPECTED TO FAIL until the Phase 3/4 de-hardcoding tasks land —
it is the enforcement gate for those tasks, not a description of their result.

Hardened (fresh-context verify, PR1 fix batch, WARNING-1): the original list
banned `"introduccion"` only in its double-quoted source form (a single-quoted
reintroduction would bypass it undetected) and banned the margin literal only
via its former constant name `_EXPECTED_MARGIN_CM`, never the bare value
`2.5` it held (an inline `abs(val - 2.5) > 0.001` reintroduction, without
recreating the named constant, would bypass it undetected). Both gaps are
closed below and proven caught by `test_guard_catches_*` (synthetic-source
tests that do NOT touch production code).
"""

from __future__ import annotations

import inspect

from docs.domain import normative as normative_module
from docs.domain import rules as rules_module

# Every literal here is a document-type-specific value (a hardcoded expected
# comparison, a fixed section id, or a Spanish-thesis normative lexicon entry)
# that the universal-schema-harness design evacuates to template data. Every
# entry is a BARE substring (no quote characters baked in) so it matches
# regardless of the quote style (or lack of quoting, for the numeric literal)
# used to reintroduce it.
_BANISHED_LITERALS = (
    "introduccion",
    "_expected_margin_cm",
    # Bare margin value (WARNING-1): catches a reintroduced numeric comparison
    # even without recreating the named `_EXPECTED_MARGIN_CM` constant.
    "2.5",
    "margins-2-5cm-non-cover",
    "docs/extracted",
    "rules_traceability_only",
    "manual-estadia-tic",
    # Spanish first-person/subjective normative lexicons (Decision 1d) —
    # distinctive enough entries that they cannot appear in this pair of files
    # for any reason other than the banished module-level constants.
    "impresionante",
    "afortunadamente",
    "lamentablemente",
    "nosotras",
    "desarrollé",
)


def _find_banished_literals(source: str) -> list[str]:
    """Pure detector, extracted so quote-style/bare-value bypass fixes are
    independently testable against synthetic source (never against
    production code, which would defeat the guard's own purpose)."""
    lowered = source.lower()
    return [literal for literal in _BANISHED_LITERALS if literal.lower() in lowered]


def _combined_source() -> str:
    return inspect.getsource(rules_module) + "\n" + inspect.getsource(normative_module)


def test_no_estadia_or_thesis_policy_literal_in_domain_rules_or_normative():
    offenders = _find_banished_literals(_combined_source())
    assert offenders == [], f"Found banished document-type literal(s): {offenders}"


def test_guard_catches_single_quoted_introduccion_literal():
    # WARNING-1: the original list banned only '"introduccion"' (double-quoted
    # source text) -- a single-quoted reintroduction bypassed it undetected.
    synthetic_source = "if section_id != 'introduccion':\n    raise ValueError('bad')\n"
    offenders = _find_banished_literals(synthetic_source)
    assert "introduccion" in offenders


def test_guard_catches_double_quoted_introduccion_literal():
    synthetic_source = 'if section_id != "introduccion":\n    raise ValueError("bad")\n'
    offenders = _find_banished_literals(synthetic_source)
    assert "introduccion" in offenders


def test_guard_catches_bare_2_5_margin_value_without_named_constant():
    # WARNING-1: the original list banned only the constant NAME
    # (_EXPECTED_MARGIN_CM), not the value it held -- a reintroduced inline
    # comparison bypassed it undetected as long as the constant itself was
    # never recreated.
    synthetic_source = "if abs(value - 2.5) > 0.001:\n    issues.append('bad margin')\n"
    offenders = _find_banished_literals(synthetic_source)
    assert "2.5" in offenders


def test_guard_stays_silent_on_unrelated_source():
    synthetic_source = "def add(a, b):\n    return a + b\n"
    assert _find_banished_literals(synthetic_source) == []
