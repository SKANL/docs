# tests/architecture/test_spec_code_bridge.py
"""RED-first coverage for the spec-to-code bridge.

All three knowledge graphs index this repo's 105 markdown files, and all
three leave them as islands: GitNexus `Section` nodes carry only `CONTAINS`,
and graphify's AST pass produces zero `document <-> code` links. The
rationale edges it does emit come from docstrings, not from `openspec/`.

This bridge closes that gap deterministically. A spec that writes a symbol in
backticks is making an explicit reference, so the edge is EXTRACTED with
confidence 1.0 -- no LLM, no inference, no hallucinated links.

These tests need no knowledge graph: every case builds its own fixture, so
they run and enforce on a fresh clone. The graph-backed invariants live in
`test_graph_invariants.py`, which skips when no index is present.
"""

import json

import pytest
from spec_code_bridge import (
    MIN_SYMBOL_LENGTH,
    GraphUnusable,
    backticked_symbols,
    bridge_edges,
    load_graph,
    normalize_symbol,
    provenance_tier,
    read_sections,
    resolve_within,
    write_graph,
)


def _document_node(node_id="doc", source_file="openspec/specs/x/spec.md", line=1):
    return {
        "id": node_id,
        "file_type": "document",
        "node_kind": "heading",
        "source_file": source_file,
        "source_location": f"L{line}",
    }


def _code_node(node_id="code_x", label="widget()", source_file="x.py"):
    return {
        "id": node_id,
        "file_type": "code",
        "label": label,
        "source_file": source_file,
    }


# --- symbol extraction ------------------------------------------------------


def test_backticked_symbols_are_extracted():
    text = "The writer MUST call `normalize_docx_zip_timestamps` before returning."
    assert backticked_symbols(text) == {"normalize_docx_zip_timestamps"}


def test_prose_without_backticks_yields_nothing():
    """Bare prose must never create edges -- that is how a graph fills with noise."""
    text = "The writer must normalize docx zip timestamps before returning."
    assert backticked_symbols(text) == set()


def test_paths_and_attribute_chains_are_ignored():
    text = "See `openspec/specs/document-render/spec.md` and `foo.bar.baz`."
    assert backticked_symbols(text) == set()


def test_a_fenced_block_body_is_not_scanned():
    """A fence whose body sits on its own lines yields nothing.

    This falls out of the pattern forbidding newlines, not from parsing
    markdown, so it is pinned here. An earlier version of this suite claimed
    fences were ignored while asserting only on paths, leaving both the claim
    untested and the reason unrecorded.
    """
    assert backticked_symbols("Example:\n\n```\nrender_toc_section\n```\n") == set()
    assert backticked_symbols("```python\nimport build_context_files\n```") == set()


def test_an_inline_span_inside_a_fence_is_still_extracted():
    """The fence grants no exemption to a single-line span written within it.

    Recorded as the known limit of a cheap pattern: a spec showing sample code
    that contains inline spans will contribute edges from that sample.
    """
    assert backticked_symbols("```\nfoo `render_toc_section` bar\n```") == {
        "render_toc_section"
    }


def test_min_symbol_length_is_enforced_at_the_boundary():
    """Pin the threshold: a silent change here would flood the graph with noise."""
    just_under = "a" * (MIN_SYMBOL_LENGTH - 1)
    exactly_at = "a" * MIN_SYMBOL_LENGTH
    assert backticked_symbols(f"`{just_under}`") == set()
    assert backticked_symbols(f"`{exactly_at}`") == {exactly_at}


def test_normalize_strips_call_and_attribute_syntax():
    assert normalize_symbol("._resolve_ambiguous_stem()") == "_resolve_ambiguous_stem"
    assert normalize_symbol("build_context_files()") == "build_context_files"


# --- edge building ----------------------------------------------------------


def test_bridge_links_spec_heading_to_matching_code_node():
    graph = {
        "nodes": [
            _document_node("spec_render", "openspec/specs/document-render/spec.md"),
            _code_node(
                "src_docs_infrastructure_docx_deterministic_zip_normalize_docx_zip_timestamps",
                "normalize_docx_zip_timestamps()",
                "src/docs/infrastructure/docx/deterministic_zip.py",
            ),
        ],
        "links": [],
    }
    sections = {
        (
            "openspec/specs/document-render/spec.md",
            1,
        ): "Uses `normalize_docx_zip_timestamps` here."
    }

    edges = bridge_edges(graph, sections)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["source"] == "spec_render"
    assert edge["target"].endswith("normalize_docx_zip_timestamps")
    assert edge["relation"] == "references"
    assert edge["confidence"] == "EXTRACTED"
    assert edge["confidence_score"] == 1.0


def test_bridge_does_not_duplicate_an_existing_link():
    """The graph is undirected and non-multigraph: a duplicate pair collapses."""
    graph = {
        "nodes": [_document_node("spec_render"), _code_node()],
        "links": [
            {"source": "spec_render", "target": "code_x", "relation": "references"}
        ],
    }
    assert bridge_edges(graph, {("s.md", 1): "Calls `widget`."}) == []


def test_vocabulary_ignores_non_python_sources():
    """A `docs` node from pyproject.toml is a package name, not a code symbol.

    Sampling the first real run linked `plans/roadmap.md :: Completed` to the
    `docs` entry of pyproject.toml. Config files must not feed the vocabulary.
    """
    graph = {
        "nodes": [
            _document_node("spec_a"),
            _code_node("cfg", "docs", "pyproject.toml"),
        ],
        "links": [],
    }
    assert bridge_edges(graph, {("s.md", 1): "Ships the `docs` package."}) == []


def test_ambiguous_symbol_links_nothing():
    """Two code nodes share a name, so attaching either one would be a guess."""
    graph = {
        "nodes": [
            _document_node("spec_a"),
            _code_node("one", "handler()", "a.py"),
            _code_node("two", "handler()", "b.py"),
        ],
        "links": [],
    }
    assert bridge_edges(graph, {("s.md", 1): "Calls `handler`."}) == []


# --- path safety ------------------------------------------------------------


def test_resolve_within_accepts_a_path_inside_the_root(tmp_path):
    (tmp_path / "spec.md").write_text("x", encoding="utf-8")
    assert resolve_within(tmp_path, "spec.md") == (tmp_path / "spec.md").resolve()


def test_resolve_within_rejects_traversal_outside_the_root(tmp_path):
    """graph.json is machine-written; a `../` entry must not become a file read."""
    root = tmp_path / "repo"
    root.mkdir()
    assert resolve_within(root, "../outside.md") is None


def test_read_sections_skips_a_traversing_source_file(tmp_path):
    """The escape target stays inside tmp_path, just outside the scanned root.

    Writing it to `tmp_path.parent` would litter the shared temp directory and
    let concurrent runs collide on the same filename.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "escape.md").write_text("# Escaped\n`secret_symbol`\n", "utf-8")
    assert read_sections([_document_node("d", "../escape.md")], root=root) == {}


# --- section slicing --------------------------------------------------------


def test_read_sections_runs_the_last_heading_to_end_of_file(tmp_path):
    (tmp_path / "s.md").write_text("# One\nalpha\n## Two\nbeta\ngamma\n", "utf-8")
    nodes = [_document_node("a", "s.md", 1), _document_node("b", "s.md", 3)]

    sections = read_sections(nodes, root=tmp_path)

    assert sections[("s.md", 1)] == "# One\nalpha"
    assert sections[("s.md", 3)] == "## Two\nbeta\ngamma"


def test_read_sections_handles_adjacent_headings(tmp_path):
    (tmp_path / "s.md").write_text("# One\n## Two\nbody\n", encoding="utf-8")
    nodes = [_document_node("a", "s.md", 1), _document_node("b", "s.md", 2)]

    sections = read_sections(nodes, root=tmp_path)

    assert sections[("s.md", 1)] == "# One"
    assert sections[("s.md", 2)] == "## Two\nbody"


def test_read_sections_skips_a_file_the_graph_names_but_the_tree_lacks(tmp_path):
    """The graph can be one rebuild behind a deletion; that is not a failure."""
    assert read_sections([_document_node("a", "gone.md", 1)], root=tmp_path) == {}


# --- graph loading and writing ---------------------------------------------


def _write_graph_file(tmp_path, payload):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_graph_rejects_a_missing_file(tmp_path):
    with pytest.raises(GraphUnusable, match="cannot read"):
        load_graph(tmp_path / "absent.json")


def test_load_graph_rejects_invalid_json(tmp_path):
    path = tmp_path / "graph.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(GraphUnusable, match="not valid JSON"):
        load_graph(path)


def test_load_graph_rejects_a_missing_links_list(tmp_path):
    """Schema drift must fail loudly, not read as 'nothing to link'."""
    path = _write_graph_file(tmp_path, {"nodes": [_document_node()]})
    with pytest.raises(GraphUnusable, match="links"):
        load_graph(path)


def test_load_graph_rejects_a_graph_with_no_document_headings(tmp_path):
    path = _write_graph_file(tmp_path, {"nodes": [_code_node()], "links": []})
    with pytest.raises(GraphUnusable, match="document heading"):
        load_graph(path)


def test_load_graph_accepts_a_well_formed_graph(tmp_path):
    payload = {"nodes": [_document_node(), _code_node()], "links": []}
    assert load_graph(_write_graph_file(tmp_path, payload))["links"] == []


def test_write_graph_replaces_the_file_and_leaves_no_temp_behind(tmp_path):
    path = _write_graph_file(tmp_path, {"nodes": [], "links": []})

    write_graph(
        {"nodes": [_code_node()], "links": [{"source": "a", "target": "b"}]}, path
    )

    assert json.loads(path.read_text(encoding="utf-8"))["links"] == [
        {"source": "a", "target": "b"}
    ]
    assert list(tmp_path.glob(".graph-*")) == []


def test_write_graph_leaves_the_original_intact_when_serialisation_fails(tmp_path):
    """A crash mid-write must not truncate the only copy of the graph."""
    original = {"nodes": [], "links": []}
    path = _write_graph_file(tmp_path, original)

    class Unserialisable:
        pass

    with pytest.raises(TypeError):
        write_graph({"nodes": [], "links": [Unserialisable()]}, path)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(tmp_path.glob(".graph-*")) == []


# --- main() -----------------------------------------------------------------


def test_main_reports_an_unusable_graph_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    """A broken graph must not exit 0 -- that reads as 'nothing to link'."""
    import spec_code_bridge

    monkeypatch.setattr(spec_code_bridge, "GRAPH", tmp_path / "absent.json")

    assert spec_code_bridge.main() == 1
    captured = capsys.readouterr()
    # Errors belong on stderr so a caller piping stdout still sees the failure.
    assert "error:" in captured.err
    assert captured.out == ""


def test_main_distinguishes_already_applied_from_nothing_matched(
    tmp_path, monkeypatch, capsys
):
    """Both write no edges; conflating them hides a bridge that stopped working."""
    import spec_code_bridge

    applied = _write_graph_file(
        tmp_path,
        {
            "nodes": [_document_node(), _code_node()],
            "links": [
                {
                    "source": "doc",
                    "target": "code_x",
                    "_origin": "spec_code_bridge",
                }
            ],
        },
    )
    monkeypatch.setattr(spec_code_bridge, "GRAPH", applied)
    monkeypatch.setattr(spec_code_bridge, "REPO_ROOT", tmp_path)
    assert spec_code_bridge.main() == 0
    assert "already present" in capsys.readouterr().out

    empty = tmp_path / "other.json"
    empty.write_text(
        json.dumps({"nodes": [_document_node(), _code_node()], "links": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(spec_code_bridge, "GRAPH", empty)
    monkeypatch.setattr(spec_code_bridge, "REPO_ROOT", tmp_path)
    assert spec_code_bridge.main() == 0
    assert "no spec->code edges matched" in capsys.readouterr().out


def test_main_writes_the_edges_it_reports(tmp_path, monkeypatch, capsys):
    import spec_code_bridge

    spec_dir = tmp_path / "openspec" / "specs" / "x"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Heading\nCalls `widget`.\n", encoding="utf-8")
    path = _write_graph_file(
        tmp_path, {"nodes": [_document_node(), _code_node()], "links": []}
    )
    monkeypatch.setattr(spec_code_bridge, "GRAPH", path)
    monkeypatch.setattr(spec_code_bridge, "REPO_ROOT", tmp_path)

    assert spec_code_bridge.main() == 0
    assert "1 spec->code edges" in capsys.readouterr().out
    written = json.loads(path.read_text(encoding="utf-8"))
    assert [link["target"] for link in written["links"]] == ["code_x"]


def test_main_recognises_its_own_edges(tmp_path, monkeypatch, capsys):
    """Round-trip the origin marker: written by one run, read by the next.

    The write side and the "already applied" side must agree on the exact
    string. If they ever drift, a bridge that had stopped producing edges would
    report "nothing matched" forever and nobody would notice.
    """
    import spec_code_bridge

    spec_dir = tmp_path / "openspec" / "specs" / "x"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Heading\nCalls `widget`.\n", encoding="utf-8")
    path = _write_graph_file(
        tmp_path, {"nodes": [_document_node(), _code_node()], "links": []}
    )
    monkeypatch.setattr(spec_code_bridge, "GRAPH", path)
    monkeypatch.setattr(spec_code_bridge, "REPO_ROOT", tmp_path)

    assert spec_code_bridge.main() == 0
    capsys.readouterr()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["links"][0]["_origin"] == spec_code_bridge.BRIDGE_ORIGIN

    assert spec_code_bridge.main() == 0
    assert "1 bridge edges already present" in capsys.readouterr().out


def test_edge_order_is_deterministic():
    """This repo demands byte-identical outputs; edge order is part of that."""
    graph = {
        "nodes": [
            _document_node("spec_a", "openspec/specs/a/spec.md"),
            _code_node("alpha_id", "alpha_thing()", "a.py"),
            _code_node("beta_id", "beta_thing()", "b.py"),
            _code_node("gamma_id", "gamma_thing()", "c.py"),
        ],
        "links": [],
    }
    sections = {("openspec/specs/a/spec.md", 1): "Calls `gamma_thing`, `alpha_thing` and `beta_thing`."}

    first = [e["target"] for e in bridge_edges(graph, sections)]
    second = [e["target"] for e in bridge_edges(graph, sections)]

    assert first == second == ["alpha_id", "beta_id", "gamma_id"]


def test_main_reports_files_the_graph_names_but_the_tree_lacks(
    tmp_path, monkeypatch, capsys
):
    """Skipping is correct; skipping in silence hides a path-wide mismatch."""
    import spec_code_bridge

    path = _write_graph_file(
        tmp_path,
        {"nodes": [_document_node("d", "gone.md"), _code_node()], "links": []},
    )
    monkeypatch.setattr(spec_code_bridge, "GRAPH", path)
    monkeypatch.setattr(spec_code_bridge, "REPO_ROOT", tmp_path)

    assert spec_code_bridge.main() == 0
    assert "1 file(s) named by the graph were unreadable" in capsys.readouterr().out


# --- provenance: the standing contract vs. the archaeology --------------------


def test_plans_are_excluded_because_the_migration_they_describe_is_finished():
    # Measured before this rule existed: 1577 of 2405 bridge edges (66%) came
    # from `plans/`, 746 from archived changes, and 25 from the STANDING
    # contract. So `graphify explain <symbol>` answered "why does this exist"
    # with a 2026-06 slice plan for a monolith migration that
    # `plans/roadmap.md` itself declares complete -- and which two later SDD
    # changes have since refactored past.
    assert provenance_tier("plans/2026-06-19-slice-1-foundations.md") is None
    assert provenance_tier("plans/roadmap.md") is None


def test_the_standing_contract_is_tier_contract():
    assert provenance_tier("openspec/specs/document-pipeline/spec.md") == "contract"
    assert provenance_tier("AGENTS.md") == "contract"
    assert provenance_tier("CLAUDE.md") == "contract"


def test_archived_changes_and_design_docs_are_tier_rationale():
    # Archived SDD changes are the ADR record CLAUDE.md calls a "full audit
    # trail" -- superseded as a PLAN, still true as a REASON.
    assert provenance_tier("openspec/changes/archive/2026-07-06-x/design.md") == "rationale"
    assert provenance_tier("specs/2026-06-19-harness-migration-hexagonal-design.md") == "rationale"


def test_every_emitted_edge_carries_its_provenance_tier():
    graph = {
        "nodes": [
            _document_node("h-spec", "openspec/specs/document-render/spec.md", 1),
            _document_node("h-plan", "plans/2026-06-19-slice-1-foundations.md", 1),
            _code_node("c1", "HtmlRendererAdapter", "src/docs/application/html_render.py"),
        ],
        "links": [],
    }
    sections = {
        ("openspec/specs/document-render/spec.md", 1): "Uses `HtmlRendererAdapter`.",
        ("plans/2026-06-19-slice-1-foundations.md", 1): "Also names `HtmlRendererAdapter`.",
    }

    edges = bridge_edges(graph, sections)

    assert [e["provenance"] for e in edges] == ["contract"]
    assert all(e["source_file"].startswith("openspec/specs/") for e in edges)
