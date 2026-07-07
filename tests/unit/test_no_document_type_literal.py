# tests/unit/test_no_document_type_literal.py
"""Structural guard (house precedent: `test_module_source_has_no_tesina_literal`)
enforcing the universal-schema-harness contract: no document-type-specific
literal (a fixed section id, a fixed policy value, or a Spanish-thesis
writing-pattern lexicon entry) may live in `domain/rules.py` or
`domain/normative.py`. All such policy MUST be declared as template data.

This test is EXPECTED TO FAIL until the Phase 3/4 de-hardcoding tasks land —
it is the enforcement gate for those tasks, not a description of their result.
"""

from __future__ import annotations

import inspect

from docs.domain import normative as normative_module
from docs.domain import rules as rules_module

# Every literal here is a document-type-specific value (a hardcoded expected
# comparison, a fixed section id, or a Spanish-thesis normative lexicon entry)
# that the universal-schema-harness design evacuates to template data.
_BANISHED_LITERALS = (
    '"introduccion"',
    "_expected_margin_cm",
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


def _combined_source() -> str:
    return (inspect.getsource(rules_module) + "\n" + inspect.getsource(normative_module)).lower()


def test_no_estadia_or_thesis_policy_literal_in_domain_rules_or_normative():
    source = _combined_source()
    offenders = [literal for literal in _BANISHED_LITERALS if literal.lower() in source]
    assert offenders == [], f"Found banished document-type literal(s): {offenders}"
