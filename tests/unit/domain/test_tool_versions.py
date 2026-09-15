# tests/unit/domain/test_tool_versions.py
"""`doctor` answered "is the tool there?" and never "is it new enough?".

That is the same mistake `safe_style_name` made about styles -- LISTED is not
USABLE -- and it cost a CI run: 13 tests died on pandoc 3.1.3 that pass on
3.10. A user with pandoc 2.9 gets `pandoc: OK` from doctor and then either a
crash or, worse, a document that quietly differs.

Pure parsing and comparison; the subprocess that reads a version lives behind
`ToolResolverPort`.
"""
from __future__ import annotations

import pytest

from docs.domain.tool_versions import MINIMUM_VERSIONS, parse_version, version_meets


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pandoc 3.10", (3, 10)),
        ("pandoc.exe 2.19.2\nCompiled with pandoc-types 1.22", (2, 19, 2)),
        ("LibreOffice 7.4.7.2 40(Build:2)", (7, 4, 7, 2)),
        ('openjdk version "17.0.9" 2023-10-17', (17, 0, 9)),
        ("11.4.0", (11, 4, 0)),
    ],
)
def test_parse_version_finds_the_number_in_real_tool_output(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "not a version", None])
def test_parse_version_returns_none_when_there_is_no_number(text):
    assert parse_version(text) is None


def test_version_meets_compares_component_wise_not_lexically():
    # `"3.10" < "3.9"` as strings, and pandoc 3.10 is newer than 3.9. A string
    # comparison here would report a modern toolchain as too old.
    assert version_meets((3, 10), (3, 9)) is True
    assert version_meets((3, 9), (3, 10)) is False


def test_version_meets_treats_a_missing_component_as_zero():
    assert version_meets((2, 19), (2, 19, 0)) is True
    assert version_meets((2, 19), (2, 19, 1)) is False


def test_version_meets_is_unknown_tolerant():
    # An unreadable version must never be reported as too old: the tool may
    # be perfectly fine and simply not answer `--version` the expected way.
    assert version_meets(None, (2, 19)) is None


def test_the_pandoc_minimum_is_the_one_the_code_actually_requires():
    # `html_render` passes `--embed-resources`, which pandoc added in 2.19.
    # The floor is derived from what the harness uses, not from taste.
    assert MINIMUM_VERSIONS["pandoc"] == (2, 19)
