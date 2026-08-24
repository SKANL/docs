# tests/architecture/test_config_vocabulary.py
"""`SCANNED_CONFIG_KEYS` must keep matching the keys the code really reads.

A hand-maintained list of known config keys is a second source of truth, and
a second source of truth rots: someone reads a new `config["..."]` in
`pipeline.py`, nobody updates the list, and near-miss detection silently
stops covering it. Silently is the exact failure mode the vocabulary exists
to remove, so it cannot be how the vocabulary itself fails.

The declaration is therefore checked against the source in BOTH directions.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from docs.domain.config_vocabulary import DYNAMICALLY_READ_KEYS, SCANNED_CONFIG_KEYS, known_keys_at

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"


def _key_path(node: ast.AST) -> tuple[str, ...] | None:
    """The config key path for an expression, or None if it is not one.

    Resolves both access styles and chains of them:
    `config["a"]["b"]` and `config.get("a", {}).get("b", {})`. A dynamic
    subscript ends the chain -- the key is not a literal, so nothing can be
    said about it here.
    """
    parts: list[str] = []
    current: Any = node
    while True:
        if isinstance(current, ast.Subscript):
            index = current.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                parts.append(index.value)
                current = current.value
                continue
            return None
        if (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr == "get"
            and current.args
            and isinstance(current.args[0], ast.Constant)
            and isinstance(current.args[0].value, str)
        ):
            parts.append(current.args[0].value)
            current = current.func.value
            continue
        if isinstance(current, ast.Name) and current.id == "config":
            return tuple(reversed(parts)) if parts else None
        if isinstance(current, ast.Attribute) and current.attr == "config":
            return tuple(reversed(parts)) if parts else None
        return None


def _scan() -> tuple[set[tuple[str, ...]], int]:
    """(distinct key paths, total accesses) across `src/docs`."""
    paths: set[tuple[str, ...]] = set()
    accesses = 0
    for path in sorted(SRC_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.Subscript, ast.Call)):
                continue
            key_path = _key_path(node)
            if key_path:
                paths.add(key_path)
                accesses += 1
    return paths, accesses


def _declared_paths(node: dict[str, Any], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for key, child in node.items():
        here = (*prefix, key)
        found.add(here)
        if isinstance(child, dict) and child:
            found |= _declared_paths(child, here)
    return found


def test_the_scan_still_finds_the_config_surface():
    # Vacuity guard. A walk that stopped matching would report perfect
    # agreement by finding nothing at all, and the vocabulary would freeze.
    _, accesses = _scan()
    assert accesses > 150, f"solo {accesses} accesos a config encontrados"


def test_every_config_key_the_code_reads_is_declared():
    scanned, _ = _scan()
    missing = sorted(".".join(p) for p in scanned - _declared_paths(SCANNED_CONFIG_KEYS))
    assert not missing, (
        f"claves de config leídas por el código pero ausentes del vocabulario: "
        f"{missing}. Sin ellas, `template validate` no puede señalar un typo "
        f"en esa clave: la trata como extensión deliberada."
    )


def test_the_vocabulary_declares_nothing_the_code_stopped_reading():
    scanned, _ = _scan()
    fictional = sorted(".".join(p) for p in _declared_paths(SCANNED_CONFIG_KEYS) - scanned)
    assert not fictional, (
        f"el vocabulario declara claves que ya nadie lee: {fictional}. "
        f"Un vocabulario con entradas muertas propone correcciones hacia "
        f"campos que no existen."
    )


def test_dynamically_read_keys_name_a_real_parent_block():
    # A dynamic entry hanging off a parent nobody reads guards nothing.
    for parent in DYNAMICALLY_READ_KEYS:
        path = tuple(parent.split("."))
        assert path in _declared_paths(SCANNED_CONFIG_KEYS), parent


def test_known_keys_at_merges_both_sources():
    margins = known_keys_at(("format", "page_margins_cm", "non_cover"))
    assert {"top", "right", "bottom", "left"} <= margins

    top_level = known_keys_at(())
    assert {"format", "paths", "output", "privacy"} <= top_level

    assert known_keys_at(("no", "such", "block")) == set()
