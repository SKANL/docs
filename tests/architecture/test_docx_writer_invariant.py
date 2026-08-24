# tests/architecture/test_docx_writer_invariant.py
"""Every `.docx`/zip writer must end in `normalize_docx_zip_timestamps`.

`CLAUDE.md` states this as the central determinism gotcha, and for good
reason: stdlib `zipfile` stamps each entry's `date_time` from
`time.localtime()` at 2-second DOS granularity, so two builds of an
identical document that straddle a 2-second boundary differ byte-for-byte.
That reads as a flaky test and is actually a product bug -- the harness
promises `.md` -> `.docx` is a byte-identical pure function (`AGENTS.md` §7).

Until now the rule lived only in prose plus one byte-identity test per
writer, added reactively each time a new write site appeared. A writer added
tomorrow gets neither.

`tests/architecture/test_graph_invariants.py` says this needs "call-path
reachability that import-level queries cannot express" -- true for full
multi-hop reachability, and irrelevant to the failure mode that actually
happens, which is a new module that never heard of the rule. An AST scan
catches that, needs no GitNexus index, and therefore never skips.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "docs"
NORMALIZER = "normalize_docx_zip_timestamps"

# The normalizer's own home: it IS the fix, so it cannot be required to call
# itself. The only exemption, and it is named rather than pattern-matched so
# a second exemption has to be argued for in a diff.
EXEMPT = {"infrastructure/docx/deterministic_zip.py"}

_ZIP_WRITE_MODES = {"w", "a", "x"}


def _writes_a_zip(tree: ast.AST) -> bool:
    """`zipfile.ZipFile(path, "w")` — any archive-creating mode."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not ast.unparse(node.func).endswith("ZipFile"):
            continue
        mode_args = [a for a in node.args[1:2] if isinstance(a, ast.Constant)]
        mode_kwargs = [
            k.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)
        ]
        for constant in mode_args + mode_kwargs:
            if isinstance(constant.value, str) and constant.value in _ZIP_WRITE_MODES:
                return True
    return False


def _saves_a_python_docx_document(tree: ast.AST, source: str) -> bool:
    """`document.save(...)` in a module that actually deals with python-docx.

    The `docx`/`docxcompose` import gate matters: `pdfium2_pdf_render_adapter`
    calls `img.save(dest)` on a PIL image, which is a PNG and has nothing to
    do with this rule.
    """
    if "docx" not in source and "docxcompose" not in source:
        return False
    return any(
        isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".save")
        for node in ast.walk(tree)
    )


def _docx_writers() -> dict[str, bool]:
    """{relative path: mentions the normalizer} for every writer found."""
    writers = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        relative = path.relative_to(SRC_ROOT.parent.parent / "src" / "docs").as_posix()
        if relative in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if _writes_a_zip(tree) or _saves_a_python_docx_document(tree, source):
            writers[relative] = NORMALIZER in source
    return writers


def test_the_scan_finds_the_known_docx_writer():
    # Vacuous-pass guard. If the AST shapes ever stop matching (a helper
    # rename, a move to another library), this reports "0 writers, all
    # compliant" and stays green while enforcing nothing.
    writers = _docx_writers()
    assert "infrastructure/docx/python_docx_assembly_adapter.py" in writers, writers


def test_every_docx_writer_routes_through_the_deterministic_zip_normalizer():
    offenders = sorted(path for path, normalized in _docx_writers().items() if not normalized)
    assert not offenders, (
        f"estos módulos escriben un .docx/zip sin pasar por `{NORMALIZER}`: "
        f"{offenders}. stdlib `zipfile` estampa la hora de pared en cada "
        f"entrada con granularidad DOS de 2 segundos, así que dos builds "
        f"idénticos que crucen ese límite difieren byte a byte — y eso "
        f"rompe la garantía de `AGENTS.md` §7. Terminá el writer en "
        f"`{NORMALIZER}(path)`, o agregalo a EXEMPT explicando por qué."
    )


def test_the_normalizer_still_exists_where_the_rule_says_it_does():
    # The rule names a specific function in a specific module. If it moves,
    # every `NORMALIZER in source` check above silently starts passing for
    # the wrong reason.
    home = SRC_ROOT / "infrastructure" / "docx" / "deterministic_zip.py"
    assert home.is_file()
    assert f"def {NORMALIZER}(" in home.read_text(encoding="utf-8")
