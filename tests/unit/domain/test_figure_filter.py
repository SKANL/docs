# tests/unit/domain/test_figure_filter.py
"""Mechanical role/size filter for figure candidates (design.md ADR-2;
spec: asset-management "Mechanical Role Filter for Figure Candidates").
Pure predicate: drops normative/example (guia-folded/reference) roles and
sub-threshold junk; fail-open on unknown role and unjudgeable (null) dims."""
from __future__ import annotations

from docs.domain.figure_filter import MIN_FIGURE_DIMENSION_PX, should_catalog_figure


def test_drops_normative_role():
    assert should_catalog_figure("normative", 640, 480) is False


def test_drops_example_role():
    assert should_catalog_figure("example", 640, 480) is False


def test_keeps_evidence_role():
    assert should_catalog_figure("evidence", 640, 480) is True


def test_keeps_unknown_role_fail_open():
    assert should_catalog_figure("unknown", 640, 480) is True


def test_drops_sub_threshold_dimensions():
    assert should_catalog_figure("evidence", MIN_FIGURE_DIMENSION_PX - 1, 50) is False


def test_keeps_dimensions_at_or_above_threshold():
    assert should_catalog_figure("evidence", MIN_FIGURE_DIMENSION_PX, 50) is True


def test_keeps_null_dimensions_fail_open():
    assert should_catalog_figure("evidence", None, None) is True
