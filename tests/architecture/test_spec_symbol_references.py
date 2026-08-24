# tests/architecture/test_spec_symbol_references.py
"""Each capability spec must name the code that implements it.

`tools/spec_code_bridge.py` turns a backticked symbol in a spec into an
EXTRACTED `references` edge, which is what lets `graphify explain <symbol>`
answer "why does this function exist" with the requirement behind it. The
bridge works. What it had to work with did not: of its 2405 edges, **25**
came from `openspec/specs/` — the CURRENT contract — while 1577 came from
`plans/` and 746 from `openspec/changes/archive/`. The "why" layer was 97%
archaeology, because the standing specs named almost no code. Five of the
twelve named none at all.

That is a property of the specs, not of the bridge, so this is where it is
checked. A spec that describes behaviour without ever naming the symbols
that provide it cannot be reached from the code, and the code cannot be
reached from it.

Anchors are FUNCTIONS, CLASSES and MODULES only — the nodes a graph can
actually traverse. A backticked `draft`, `kind` or `paths` is a field name
or a literal; it resolves by accident and anchors nothing.
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "docs"
SPECS_ROOT = REPO_ROOT / "openspec" / "specs"

sys.path.insert(0, str(REPO_ROOT / "tools"))
from spec_code_bridge import backticked_symbols

# Enough anchors to place a capability in the tree without turning the spec
# into a symbol dump. Three is one per typical layer: a port or model, the
# service that orchestrates it, and the module it lives in.
MIN_ANCHORS_PER_SPEC = 3

# `KeyError`/`ValueError` are CamelCase and real, just not OURS.
_BUILTINS = set(dir(builtins))


def _navigable_symbols() -> set[str]:
    """Every function, class and module name under `src/docs`."""
    symbols: set[str] = set()
    for path in SRC_ROOT.rglob("*.py"):
        if path.stem != "__init__":
            symbols.add(path.stem)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
    return symbols


def _anchors_per_spec() -> dict[str, list[str]]:
    symbols = _navigable_symbols()
    return {
        spec.parent.name: sorted(backticked_symbols(spec.read_text(encoding="utf-8")) & symbols)
        for spec in sorted(SPECS_ROOT.glob("*/spec.md"))
    }


def test_the_scan_finds_the_specs_and_the_code():
    # Vacuous-pass guard on both sides: a moved spec tree reports zero specs
    # (and iterating nothing passes trivially), a broken AST walk reports
    # zero symbols (and then NOTHING resolves, which would look like total
    # drift rather than a broken test).
    assert len(_anchors_per_spec()) == 12, "se esperan 12 capabilities"
    assert len(_navigable_symbols()) > 500


def test_every_capability_spec_anchors_to_the_code_that_implements_it():
    thin = {
        capability: anchors
        for capability, anchors in _anchors_per_spec().items()
        if len(anchors) < MIN_ANCHORS_PER_SPEC
    }
    assert not thin, (
        f"estas capabilities nombran menos de {MIN_ANCHORS_PER_SPEC} símbolos "
        f"reales del código: {thin}. Sin al menos ese ancla, "
        f"`tools/spec_code_bridge.py` no puede conectarlas con su "
        f"implementación y `graphify explain <symbol>` devuelve planes "
        f"viejos en vez del contrato vigente. Nombrá en backticks los "
        f"puertos, servicios o módulos que cada requisito describe."
    )


def test_no_spec_anchors_to_a_symbol_that_no_longer_exists():
    # The other drift direction: a spec that keeps naming `DocumentRepository`
    # methods after a refactor points the bridge at nothing. Only names that
    # LOOK like code symbols are checked -- prose words in backticks (config
    # keys, literals, CLI fragments) are legitimate and ignored.
    symbols = _navigable_symbols()
    ghosts: dict[str, list[str]] = {}
    for spec in sorted(SPECS_ROOT.glob("*/spec.md")):
        named = backticked_symbols(spec.read_text(encoding="utf-8"))
        # CamelCase or snake_case-with-a-verb: the shapes only code uses.
        code_shaped = {
            name
            for name in named
            if name not in _BUILTINS
            and not name.isupper()  # `PENDIENTE` and friends are literals, not symbols
            and (
                (name[:1].isupper() and any(c.isupper() for c in name[1:]))
                or name.startswith(("build_", "resolve_", "render_", "review_", "apply_", "normalize_"))
            )
        }
        missing = sorted(code_shaped - symbols)
        if missing:
            ghosts[spec.parent.name] = missing
    assert not ghosts, (
        f"specs que nombran símbolos inexistentes: {ghosts}. O se renombraron "
        f"en el código y el contrato quedó viejo, o nunca existieron."
    )
