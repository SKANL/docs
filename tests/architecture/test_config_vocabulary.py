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


def _literal_string_lists(tree: ast.AST) -> dict[str, list[str]]:
    """Names bound to a list of string literals, or of tuples of them.

    Both blind-spot sites in this codebase use that shape: `doctor` writes
    `for name in ["template_docx", ...]` and `evidence` writes
    `_TRACEABILITY_PATH_KEYS = [("manual_pdf", "institutional_pdf"), ...]`.
    Resolving the binding is what lets the scan see keys that are loop
    variables by the time `config.get()` receives them.
    """
    bound: dict[str, list[str]] = {}

    def strings(node: ast.AST) -> list[str]:
        if isinstance(node, (ast.List, ast.Tuple)):
            found: list[str] = []
            for item in node.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    found.append(item.value)
                else:
                    found.extend(strings(item))
            return found
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            values = strings(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and values:
                    bound[target.id] = values
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            values = strings(node.iter)
            if values:
                bound[node.target.id] = values
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            values = strings(node.iter)
            for element in node.target.elts:
                if isinstance(element, ast.Name) and values:
                    bound[element.id] = values
    return bound


def _config_aliases(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    """Local names bound to a slice of `config`, and the path they stand for.

    `status.py` writes `paths = config["paths"]` and then
    `paths.get("output_final_dir")`. Rooting the scan on the name `config`
    alone made nineteen legitimate keys invisible -- every toolchain override
    and the final output directory among them -- and near-miss detection then
    reported `paths.output_final_dir` as a probable typo of `output_qa_dir`.
    That is the same advice that got a live key renamed out of a shipped
    template, so the shape is resolved rather than merely documented.
    """
    aliases: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        key_path = _key_path(node.value)
        if key_path:
            aliases[target.id] = key_path
    return aliases


def _scan() -> tuple[set[tuple[str, ...]], int]:
    """(distinct key paths, total accesses) across `src/docs`."""
    paths: set[tuple[str, ...]] = set()
    accesses = 0
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bound = _literal_string_lists(tree)
        aliases = _config_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Subscript, ast.Call)):
                continue
            key_path = _key_path(node)
            if key_path:
                paths.add(key_path)
                accesses += 1
                continue
            # `config["paths"].get(name)` where `name` iterates a literal
            # list: the prefix resolves, the final key does not, and every
            # value the name can hold is a key the code reads.
            prefix = _key_path(_receiver(node)) or _alias_prefix(_receiver(node), aliases)
            if prefix is None:
                continue
            # A literal key read off an alias: `paths.get("output_final_dir")`.
            literal = _literal_key(node)
            if literal:
                paths.add((*prefix, literal))
                accesses += 1
            if prefix:
                for candidate in bound.get(_dynamic_key_name(node) or "", ()):
                    paths.add((*prefix, candidate))
                    accesses += 1
    return paths, accesses



def _alias_prefix(node: ast.AST | None, aliases: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    """The config path a local alias stands for, when the receiver is one."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    return None


def _literal_key(node: ast.AST) -> str | None:
    """The string key of a `[...]` / `.get(...)` access, when it is literal."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        value = node.slice.value
        return value if isinstance(value, str) else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None

def _receiver(node: ast.AST) -> ast.AST | None:
    """The expression a dynamic `[x]` / `.get(x)` is reading FROM."""
    if isinstance(node, ast.Subscript):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return node.func.value
    return None


def _dynamic_key_name(node: ast.AST) -> str | None:
    """The variable name used as the key, when the key is not a literal."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Name):
        return node.slice.id
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Name)
    ):
        return node.args[0].id
    return None


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


def test_keys_read_through_a_loop_variable_are_still_declared():
    # The regression this prevents was mine. `paths.manual_pdf` is read twice
    # -- `doctor` loops over a literal list of key names, and
    # `evidence._TRACEABILITY_PATH_KEYS` is a module-level list of pairs --
    # and the plain AST scan sees neither, because by the time `.get()` runs
    # the key is a loop variable.
    #
    # The vocabulary was therefore missing it, near-miss detection reported a
    # LIVE key as a typo of `manual_dir`, and I renamed it out of a shipped
    # template on that advice. Blind spots are fine when they are known and
    # declared; this asserts the declaration is complete for the idiom that
    # actually bit.
    for key in ("template_docx", "example_pdf", "manual_pdf"):
        assert key in known_keys_at(("paths",)), (
            f"paths.{key} lo lee `doctor`/`evidence` a través de una lista "
            f"literal; sin declararlo, el chequeo de casi-coincidencias lo "
            f"trata como typo de una clave real."
        )


def test_keys_read_through_a_local_alias_are_still_declared():
    # Third time this blind spot cost something. `status.py` writes
    # `paths = config["paths"]` and then `paths.get("output_final_dir")`; the
    # scan rooted on the name `config`, so nineteen legitimate keys were
    # invisible -- every toolchain override (`pandoc_bin`, `java_fallbacks`,
    # ...) and the final output directory among them.
    #
    # Measured consequence before the fix: a template declaring
    # `paths.output_final_dir` was told it was probably a typo of
    # `output_qa_dir`. That is exactly the advice that made me rename a live
    # key out of a shipped template. Declaring blind spots is not enough when
    # something acts on the output; this one is closed instead.
    declared = known_keys_at(("paths",))
    for key in ("output_final_dir", "pandoc_bin", "pandoc_fallbacks", "libreoffice_bin", "java_bin"):
        assert key in declared, f"paths.{key} se lee vía alias local y no está declarada"


def test_no_real_config_key_is_reported_as_a_typo():
    # The end-to-end property all of this exists for: a template declaring
    # keys the harness actually reads must produce ZERO near-miss findings.
    from docs.domain.template_validation import validate_template

    raw = {
        "type": "t", "title": "T",
        "sections": [{"id": "a", "title": "A", "order": 1}],
        "section_contracts": {"a": {}},
        "context_schema": {"topics": []},
        "paths": dict.fromkeys(sorted(known_keys_at(("paths",))), "x"),
    }
    near = [i for i in validate_template(raw) if i.code == "template.unknown_key"]
    assert near == [], [i.message for i in near]
