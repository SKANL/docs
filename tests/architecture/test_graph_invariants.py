# tests/architecture/test_graph_invariants.py
"""Architecture invariants enforced against the GitNexus knowledge graph.

`CLAUDE.md` states several rules ("learned the hard way") that until now were
enforced only by prose and human memory: the hexagonal dependency direction,
and the determinism guarantee of the `.docx` writers. Verifying them by hand
costs several greps and a careful read of temp-vs-final write targets.

These tests turn that prose into mechanical checks. They query the GitNexus
graph (`gitnexus analyze --index-only --pdg`), which carries the IMPORTS
edges resolved across the whole tree.

The suite stays hermetic: when the graph is absent (fresh clone, CI without
an index) every test skips rather than failing. That makes vacuous passes the
real hazard, so `test_probe_finds_known_import_edges` asserts the query
mechanism can still return rows -- a green suite built on a broken query is
worse than a red one.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GITNEXUS = shutil.which("gitnexus")


def _index_present() -> bool:
    return (REPO_ROOT / ".gitnexus").is_dir()


requires_graph = pytest.mark.skipif(
    GITNEXUS is None or not _index_present(),
    reason="GitNexus graph unavailable; run `gitnexus analyze --index-only --pdg`",
)


def _parse_markdown_table(markdown: str) -> list[dict[str, str]]:
    """GitNexus returns result sets as a markdown table; turn it into dicts."""
    lines = [ln for ln in markdown.splitlines() if ln.startswith("|")]
    if len(lines) < 2:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip the |---|---| separator
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(dict(zip(header, cells)))
    return rows


def cypher(query: str, limit: int = 200) -> list[dict[str, str]]:
    """Run a Cypher query against the GitNexus graph and return its rows.

    An empty result set comes back as a bare `[]`; a populated one as
    `{"markdown": ..., "row_count": N}`. A malformed query returns
    `{"error": ...}` and must fail loudly -- silently treating an error as
    "no violations" is exactly how these checks would rot into vacuity.
    """
    completed = subprocess.run(
        [GITNEXUS, "cypher", query, "-l", str(limit)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    payload = json.loads(completed.stdout)
    if isinstance(payload, list):
        return []
    if "error" in payload:
        raise RuntimeError(f"GitNexus rejected the query: {payload['error']}")
    return _parse_markdown_table(payload.get("markdown", ""))


IMPORT_EDGE = (
    "MATCH (a:File)-[r:CodeRelation]->(b:File) "
    "WHERE r.type = 'IMPORTS' "
    "AND a.filePath STARTS WITH '{src}' "
    "AND b.filePath STARTS WITH '{dst}' "
    "RETURN a.filePath AS importer, b.filePath AS imported"
)


@requires_graph
def test_probe_finds_known_import_edges():
    """Guard against vacuous passes: the query mechanism must still find rows.

    `infrastructure -> domain` is the legitimate direction and demonstrably
    exists. If this ever returns nothing, the graph or the query shape broke,
    and every "no violations" result below is meaningless.
    """
    rows = cypher(
        IMPORT_EDGE.format(src="src/docs/infrastructure/", dst="src/docs/domain/")
    )
    assert rows, "graph returned no infrastructure->domain imports; query is broken"


@requires_graph
@pytest.mark.parametrize("inner", ["src/docs/domain/", "src/docs/application/"])
def test_inner_layers_never_import_infrastructure(inner: str):
    """CLAUDE.md: `cli -> application -> domain`; infrastructure implements ports.

    Nothing in domain or application may reach for a concrete adapter.
    """
    violations = cypher(IMPORT_EDGE.format(src=inner, dst="src/docs/infrastructure/"))
    assert not violations, (
        f"hexagonal boundary broken -- {inner} imports infrastructure:\n"
        + "\n".join(f"  {v['importer']} -> {v['imported']}" for v in violations)
    )
