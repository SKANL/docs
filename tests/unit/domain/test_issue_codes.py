# tests/unit/domain/test_issue_codes.py
"""The review loop's vocabulary must be documented, and stay documented.

`AGENTS.md` §4 tells the agent to run `review-section --json` and iterate to
green. That loop emits 31 distinct `code` values; exactly ONE of them was
ever documented anywhere. The agent receives `coherence.duration_mismatch`
and has to guess both what it means and how to clear it.

The catalog fixes that. These tests keep it honest in BOTH directions: a new
code that nobody documented fails, and a documented code that no longer
exists fails too -- so the catalog can never drift into fiction.
"""
from __future__ import annotations

import ast
from pathlib import Path

from docs.domain.issue_codes import ISSUE_CODE_FAMILIES, ISSUE_CODES, explain_code

SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "docs"


def _codes_emitted_by_the_code() -> set[str]:
    """Every string literal passed as `code=` anywhere under `src/docs`."""
    emitted: set[str] = set()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "code":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    emitted.add(keyword.value.value)
    return emitted


def test_the_scan_finds_the_issue_code_surface():
    # Vacuous-pass guard: an AST walk that stopped matching would report
    # "nothing undocumented" forever.
    assert len(_codes_emitted_by_the_code()) >= 30


def test_every_emitted_code_is_documented():
    undocumented = sorted(_codes_emitted_by_the_code() - set(ISSUE_CODES))
    assert not undocumented, (
        f"códigos emitidos sin entrada en el catálogo: {undocumented}. "
        f"Agregalos a `docs.domain.issue_codes.ISSUE_CODES` — el agente los "
        f"recibe en `review-section --json` y no puede accionarlos sin saber "
        f"qué significan."
    )


def test_every_documented_code_is_actually_emitted():
    fictional = sorted(set(ISSUE_CODES) - _codes_emitted_by_the_code())
    assert not fictional, (
        f"el catálogo documenta códigos que ya nadie emite: {fictional}. "
        f"Un catálogo con entradas muertas enseña cosas falsas."
    )


def test_every_entry_says_what_it_means_and_what_to_do():
    thin = [
        code
        for code, entry in ISSUE_CODES.items()
        if len(entry.meaning.split()) < 4 or len(entry.fix.split()) < 4
    ]
    assert not thin, f"entradas sin explicación accionable: {thin}"


def test_explain_code_returns_the_catalog_entry():
    text = explain_code("content.pending_not_allowed")
    assert "content.pending_not_allowed" in text
    assert ISSUE_CODES["content.pending_not_allowed"].meaning in text
    assert ISSUE_CODES["content.pending_not_allowed"].fix in text


def test_explain_code_suggests_near_matches_for_an_unknown_code():
    # A typo'd or half-remembered code is the common case for an agent
    # reading a truncated log. Failing with "unknown" alone wastes a turn.
    text = explain_code("content.pending")
    assert "content.pending_not_allowed" in text


def test_explain_code_without_argument_lists_the_whole_catalog():
    text = explain_code(None)
    for code in ISSUE_CODES:
        assert code in text


def test_codes_are_grouped_by_a_documented_prefix():
    prefixes = {code.split(".")[0] for code in ISSUE_CODES}
    assert prefixes <= set(ISSUE_CODE_FAMILIES), (
        f"familias de código sin documentar: {sorted(prefixes - set(ISSUE_CODE_FAMILIES))}"
    )
