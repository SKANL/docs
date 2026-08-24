# tests/architecture/test_spec_code_bridge.py
"""RED-first coverage for the spec-to-code bridge.

All three knowledge graphs index this repo's 105 markdown files, and all
three leave them as islands: GitNexus `Section` nodes carry only `CONTAINS`,
and graphify's AST pass produces zero `document <-> code` links. The
rationale edges it does emit come from docstrings, not from `openspec/`.

This bridge closes that gap deterministically. A spec that writes a symbol in
backticks is making an explicit reference, so the edge is EXTRACTED with
confidence 1.0 -- no LLM, no inference, no hallucinated links.
"""

from spec_code_bridge import backticked_symbols, bridge_edges, normalize_symbol


def test_backticked_symbols_are_extracted():
    text = "The writer MUST call `normalize_docx_zip_timestamps` before returning."
    assert backticked_symbols(text) == {"normalize_docx_zip_timestamps"}


def test_prose_without_backticks_yields_nothing():
    """Bare prose must never create edges -- that is how a graph fills with noise."""
    text = "The writer must normalize docx zip timestamps before returning."
    assert backticked_symbols(text) == set()


def test_code_fences_and_paths_are_ignored():
    text = "See `openspec/specs/document-render/spec.md` and `foo.bar.baz`."
    assert backticked_symbols(text) == set()


def test_normalize_strips_call_and_attribute_syntax():
    assert normalize_symbol("._resolve_ambiguous_stem()") == "_resolve_ambiguous_stem"
    assert normalize_symbol("build_context_files()") == "build_context_files"


def test_bridge_links_spec_heading_to_matching_code_node():
    graph = {
        "nodes": [
            {
                "id": "spec_render",
                "file_type": "document",
                "node_kind": "heading",
                "source_file": "openspec/specs/document-render/spec.md",
                "source_location": "L1",
            },
            {
                "id": "src_docs_infrastructure_docx_deterministic_zip_normalize_docx_zip_timestamps",
                "file_type": "code",
                "label": "normalize_docx_zip_timestamps()",
                "source_file": "src/docs/infrastructure/docx/deterministic_zip.py",
            },
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
        "nodes": [
            {
                "id": "spec_render",
                "file_type": "document",
                "node_kind": "heading",
                "source_file": "s.md",
                "source_location": "L1",
            },
            {
                "id": "code_x",
                "file_type": "code",
                "label": "widget()",
                "source_file": "x.py",
            },
        ],
        "links": [
            {"source": "spec_render", "target": "code_x", "relation": "references"}
        ],
    }
    sections = {("s.md", 1): "Calls `widget`."}

    assert bridge_edges(graph, sections) == []


def test_vocabulary_ignores_non_python_sources():
    """A `docs` node from pyproject.toml is a package name, not a code symbol.

    Sampling the first real run linked `plans/roadmap.md :: Completed` to the
    `docs` entry of pyproject.toml. Config files must not feed the vocabulary.
    """
    graph = {
        "nodes": [
            {
                "id": "spec_a",
                "file_type": "document",
                "node_kind": "heading",
                "source_file": "s.md",
                "source_location": "L1",
            },
            {
                "id": "cfg",
                "file_type": "code",
                "label": "docs",
                "source_file": "pyproject.toml",
            },
        ],
        "links": [],
    }
    assert bridge_edges(graph, {("s.md", 1): "Ships the `docs` package."}) == []
