# tests/architecture/test_graph_invariants.py
"""The hexagonal dependency rule, enforced against the GitNexus graph.

`CLAUDE.md` states the layering rule -- `cli -> application -> domain`, with
infrastructure implementing domain ports -- as prose, enforced until now only
by human memory. This module turns that one rule into a mechanical check by
querying the GitNexus graph (`gitnexus analyze --index-only --pdg`), whose
IMPORTS edges are resolved across the whole tree.

Scope is deliberately narrow: only the layering rule is checked here. The
determinism guarantees around the `.docx` writers are NOT covered -- they need
call-path reachability that these import-level queries cannot express.

Without an index every test skips, so a fresh clone stays green. That makes a
vacuous pass the real hazard, guarded two ways: `test_probe_finds_known_import_edges`
proves the query still returns rows, and setting `ARCHITECTURE_REQUIRE_GRAPH`
to any enabling value turns a missing index from a skip into a failure, so CI
can demand enforcement rather than silently accepting nothing. No pipeline in
this repo sets it yet -- there is no CI configuration to wire it into.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GITNEXUS = shutil.which("gitnexus")

# GitNexus stores repo-relative paths with forward slashes on every platform.
# `test_probe_finds_known_import_edges` is the only backstop: it uses these same
# prefixes, so a separator change makes it return nothing and fail. It cannot
# distinguish that from any other cause -- it proves the prefixes still match
# something, not why they stopped.
SRC_DOMAIN = "src/docs/domain/"
SRC_APPLICATION = "src/docs/application/"
SRC_INFRASTRUCTURE = "src/docs/infrastructure/"


def _index_present() -> bool:
    return (REPO_ROOT / ".gitnexus").is_dir()


def _graph_available() -> bool:
    return GITNEXUS is not None and _index_present()


# Anything but these means "enforce". A CI job that sets the flag to `true` or
# `yes` must not be silently ignored: a switch that quietly fails open is worse
# than no switch, because the pipeline reports a guarantee it never had.
_DISABLED_VALUES = {"", "0", "false", "no", "off"}


def _require_graph() -> bool:
    """Whether a missing index must fail instead of skip (CI opt-in)."""
    raw = os.environ.get("ARCHITECTURE_REQUIRE_GRAPH")
    if raw is None:
        return False
    return raw.strip().lower() not in _DISABLED_VALUES


def _needs_graph() -> None:
    """Skip, or fail when the caller demanded enforcement."""
    if _graph_available():
        return
    message = "GitNexus graph unavailable; run `gitnexus analyze --index-only --pdg`"
    if _require_graph():
        pytest.fail(f"ARCHITECTURE_REQUIRE_GRAPH=1 but {message}")
    pytest.skip(message)


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


def parse_cypher_output(completed: subprocess.CompletedProcess) -> list[dict[str, str]]:
    """Turn one finished `gitnexus cypher` run into rows, or fail loudly.

    Every failure mode here would otherwise read as "no violations": a crashed
    binary, a rejected query, or output that is not JSON at all. Each one must
    raise, and must carry the diagnostics needed to tell them apart -- an
    architecture check that passes because the tool broke is worse than absent.
    """
    if completed.returncode != 0:
        raise RuntimeError(
            f"gitnexus cypher exited {completed.returncode}: "
            f"{(completed.stderr or '').strip() or '<no stderr>'}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"gitnexus cypher returned non-JSON output: {exc}; "
            f"stdout={completed.stdout[:200]!r} "
            f"stderr={(completed.stderr or '').strip()[:200]!r}"
        ) from exc
    if isinstance(payload, list):
        return []  # an empty result set comes back as a bare []
    if "error" in payload:
        raise RuntimeError(f"GitNexus rejected the query: {payload['error']}")
    if "markdown" not in payload:
        raise RuntimeError(
            "GitNexus returned a result object without a 'markdown' key; its "
            f"output shape changed and rows can no longer be read: {sorted(payload)}"
        )
    return _parse_markdown_table(payload["markdown"])


def cypher_argv(query: str, limit: int) -> list[str]:
    """Build the exact `gitnexus cypher` argv, naming the repo explicitly.

    GitNexus keeps a machine-global registry, so `cypher` refuses to guess once
    a second repository is indexed anywhere on the box ("Multiple repositories
    indexed. Specify which one with the repo parameter"). Being inside the repo
    is not enough. `REPO_ROOT.name` is the label `gitnexus analyze` registers by
    default; a repo indexed under `--name <alias>` needs that alias instead.
    """
    return [
        GITNEXUS,
        "cypher",
        query,
        "-l",
        str(limit),
        "--repo",
        REPO_ROOT.name,
    ]


def cypher(query: str, limit: int = 200) -> list[dict[str, str]]:
    """Run a Cypher query against the GitNexus graph and return its rows."""
    completed = subprocess.run(
        cypher_argv(query, limit),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return parse_cypher_output(completed)


IMPORT_EDGE = (
    "MATCH (a:File)-[r:CodeRelation]->(b:File) "
    "WHERE r.type = 'IMPORTS' "
    "AND a.filePath STARTS WITH '{src}' "
    "AND b.filePath STARTS WITH '{dst}' "
    "RETURN a.filePath AS importer, b.filePath AS imported"
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["gitnexus"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- output handling (runs without a graph) --------------------------------


def test_process_failure_raises_and_keeps_the_diagnostics():
    """A crashed binary must never be mistaken for a clean architecture."""
    with pytest.raises(RuntimeError, match="exited 3") as raised:
        parse_cypher_output(_completed(returncode=3, stderr="kuzu: lock held"))
    assert "kuzu: lock held" in str(raised.value)


def test_non_json_output_raises_rather_than_reading_as_clean():
    with pytest.raises(RuntimeError, match="non-JSON"):
        parse_cypher_output(_completed(stdout="Error: something went wrong"))


def test_rejected_query_raises():
    payload = json.dumps({"error": "Binder exception: no property filePath"})
    with pytest.raises(RuntimeError, match="rejected the query"):
        parse_cypher_output(_completed(stdout=payload))


def test_empty_result_set_is_no_violations():
    assert parse_cypher_output(_completed(stdout="[]")) == []


def test_rows_are_parsed_from_the_markdown_table():
    payload = json.dumps({"markdown": "| a | b |\n| --- | --- |\n| x.py | y.py |"})
    assert parse_cypher_output(_completed(stdout=payload)) == [
        {"a": "x.py", "b": "y.py"}
    ]


def test_result_object_without_a_markdown_key_raises():
    """Key drift must not degrade into zero rows, which reads as 'clean'."""
    payload = json.dumps({"rows": [], "row_count": 0})
    with pytest.raises(RuntimeError, match="without a 'markdown' key"):
        parse_cypher_output(_completed(stdout=payload))


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_enforcement_accepts_any_enabling_value(monkeypatch, value):
    """A flag that quietly fails open on `true` is worse than no flag at all."""
    monkeypatch.setenv("ARCHITECTURE_REQUIRE_GRAPH", value)
    assert _require_graph() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_enforcement_stays_off_for_disabling_values(monkeypatch, value):
    monkeypatch.setenv("ARCHITECTURE_REQUIRE_GRAPH", value)
    assert _require_graph() is False


def test_enforcement_is_off_when_unset(monkeypatch):
    monkeypatch.delenv("ARCHITECTURE_REQUIRE_GRAPH", raising=False)
    assert _require_graph() is False


def test_missing_graph_fails_when_enforcement_is_demanded(monkeypatch):
    """CI can require the check instead of accepting a silent skip."""
    monkeypatch.setenv("ARCHITECTURE_REQUIRE_GRAPH", "1")
    monkeypatch.setattr(sys.modules[__name__], "_graph_available", lambda: False)
    with pytest.raises(pytest.fail.Exception, match="ARCHITECTURE_REQUIRE_GRAPH"):
        _needs_graph()


def test_missing_graph_skips_when_enforcement_is_not_demanded(monkeypatch):
    monkeypatch.delenv("ARCHITECTURE_REQUIRE_GRAPH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "_graph_available", lambda: False)
    with pytest.raises(pytest.skip.Exception):
        _needs_graph()


# --- the invariant itself (needs the graph) --------------------------------


def test_probe_finds_known_import_edges():
    """Guard against vacuous passes: the query mechanism must still find rows.

    `infrastructure -> domain` is the legitimate direction and demonstrably
    exists. If this returns nothing, the graph, the path separators or the
    query shape broke, and every "no violations" result below is meaningless.
    """
    _needs_graph()
    rows = cypher(IMPORT_EDGE.format(src=SRC_INFRASTRUCTURE, dst=SRC_DOMAIN))
    assert rows, "graph returned no infrastructure->domain imports; query is broken"


@pytest.mark.parametrize("inner", [SRC_DOMAIN, SRC_APPLICATION])
def test_inner_layers_never_import_infrastructure(inner: str):
    """CLAUDE.md: `cli -> application -> domain`; infrastructure implements ports.

    Nothing in domain or application may reach for a concrete adapter.
    """
    _needs_graph()
    violations = cypher(IMPORT_EDGE.format(src=inner, dst=SRC_INFRASTRUCTURE))
    assert not violations, (
        f"hexagonal boundary broken -- {inner} imports infrastructure:\n"
        + "\n".join(f"  {v['importer']} -> {v['imported']}" for v in violations)
    )


def test_cypher_argv_names_the_repository():
    """Regression: without --repo, every query dies once a second repo is indexed.

    A machine-global GitNexus registry made `gitnexus cypher` refuse to guess
    ("Multiple repositories indexed"), and running from inside the repo does
    not disambiguate it. The returncode check above is what surfaced this as a
    loud failure rather than a confusing parse error.
    """
    argv = cypher_argv("MATCH (f:File) RETURN f", 5)

    assert "--repo" in argv
    assert argv[argv.index("--repo") + 1] == REPO_ROOT.name
    assert argv[1] == "cypher"
    assert argv[argv.index("-l") + 1] == "5"
