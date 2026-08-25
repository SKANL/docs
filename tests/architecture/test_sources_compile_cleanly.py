# tests/architecture/test_sources_compile_cleanly.py
"""Every source file must compile without a warning, from a cold cache.

`filterwarnings = ["error"]` catches a bad escape sequence -- but only when
Python actually COMPILES the file. Python caches bytecode, so a locally warm
`__pycache__` means the compile never happens and the warning never fires:
the suite passed clean on this machine while CI, with a fresh checkout,
failed on two more of them.

That is a check whose strength depends on how recently someone cleared a
cache, which is no check at all. This one compiles the source text directly,
so it is as strong on a developer's tenth run as on CI's first.
"""
from __future__ import annotations

import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("src", "tests", "tools")


def _sources() -> list[Path]:
    return sorted(
        path
        for root in ROOTS
        for path in (REPO_ROOT / root).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_the_scan_finds_the_source_tree():
    # Vacuity guard: a glob that stopped matching would report every file
    # clean by finding none.
    assert len(_sources()) > 150


def test_no_source_file_compiles_with_a_warning():
    offenders: list[str] = []
    for path in _sources():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for warning in caught:
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{warning.lineno} {warning.message}")

    assert not offenders, (
        "estos archivos compilan con advertencia:\n  " + "\n  ".join(offenders) +
        "\n\nUna secuencia de escape invalida (backslash-L, backslash-o, ...) pasa ruff y "
        "mypy, y en Python 3.12+ es un SyntaxError. Usa un raw string, o barras "
        "normales si es prosa."
    )
