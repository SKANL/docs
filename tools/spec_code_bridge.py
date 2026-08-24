"""Link openspec prose to the code it describes, deterministically.

All three knowledge graphs indexing this repo leave the 105 markdown files as
islands. GitNexus gives `Section` nodes only `CONTAINS` edges; graphify's AST
pass emits zero `document <-> code` links (its `rationale_for` edges come from
docstrings, not from `openspec/`). So "which code implements this requirement"
is unanswerable in every one of them.

This bridge answers it without an LLM. When a spec writes a symbol in
backticks it is making an explicit reference, so the edge is EXTRACTED with
confidence 1.0. Prose mentions are deliberately ignored: an inferred edge here
would be a guess wearing the costume of a fact, and the graph is only worth
traversing while its edges are trustworthy.

Edges are written straight into `graphify-out/graph.json`. `graphify
merge-graphs` is NOT usable here: it is built for cross-repo merges and
namespaces the second graph's ids (`repo-2::...`), forking every endpoint
into a ghost duplicate instead of attaching to the node it names.

Re-running is safe -- an edge whose endpoint pair already exists is skipped.

Usage:
    python tools/spec_code_bridge.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH = REPO_ROOT / "graphify-out" / "graph.json"

# A bare identifier only: anything with a dot, slash or space is a path, an
# attribute chain or a signature, and matching those invites false edges.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKTICKED = re.compile(r"`([^`\n]+)`")

# ponytail: short names like `path` or `name` collide across the tree and would
# bury real references in noise. Four characters is the cheap cutoff; tighten it
# only if a real symbol ever gets skipped.
MIN_SYMBOL_LENGTH = 4


def normalize_symbol(label: str) -> str:
    """Reduce a graphify code label (`._resolve()`, `build()`) to its name."""
    return label.strip().lstrip(".").removesuffix("()")


def backticked_symbols(text: str) -> set[str]:
    """Return the bare identifiers a document explicitly names in backticks."""
    found = set()
    for raw in _BACKTICKED.findall(text):
        candidate = normalize_symbol(raw)
        if len(candidate) >= MIN_SYMBOL_LENGTH and _IDENTIFIER.match(candidate):
            found.add(candidate)
    return found


def _code_vocabulary(nodes: list[dict]) -> dict[str, str]:
    """Map symbol name -> code node id, dropping names that are not unique.

    An ambiguous name would attach a requirement to whichever node happened to
    be seen last, which is worse than leaving the requirement unlinked.
    """
    seen: dict[str, str | None] = {}
    for node in nodes:
        if node.get("file_type") != "code":
            continue
        # graphify labels config files as code too, so `docs` from pyproject.toml
        # would shadow real symbols. This repo's source is Python; nothing else
        # defines a symbol a spec could legitimately reference.
        if not str(node.get("source_file", "")).endswith(".py"):
            continue
        name = normalize_symbol(str(node.get("label", "")))
        if not _IDENTIFIER.match(name):
            continue
        seen[name] = None if name in seen else node["id"]
    return {name: node_id for name, node_id in seen.items() if node_id}


def bridge_edges(graph: dict, sections: dict[tuple[str, int], str]) -> list[dict]:
    """Build `references` edges from document headings to the code they name."""
    nodes = graph["nodes"]
    vocabulary = _code_vocabulary(nodes)
    # The graph is undirected and non-multigraph, so a repeated endpoint pair
    # silently collapses onto the existing edge instead of adding information.
    existing = {
        frozenset((link["source"], link["target"])) for link in graph.get("links", [])
    }

    edges: list[dict] = []
    for node in nodes:
        if node.get("file_type") != "document" or node.get("node_kind") != "heading":
            continue
        source_file = node.get("source_file")
        location = str(node.get("source_location") or "").lstrip("L")
        if not source_file or not location.isdigit():
            continue
        text = sections.get((source_file, int(location)))
        if not text:
            continue
        for symbol in sorted(backticked_symbols(text)):
            target = vocabulary.get(symbol)
            if not target or frozenset((node["id"], target)) in existing:
                continue
            existing.add(frozenset((node["id"], target)))
            edges.append(
                {
                    "source": node["id"],
                    "target": target,
                    "relation": "references",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "context": "spec_reference",
                    "source_file": source_file,
                    "source_location": f"L{location}",
                    "weight": 1.0,
                    "_origin": "spec_code_bridge",
                }
            )
    return edges


def read_sections(
    nodes: list[dict], root: Path = REPO_ROOT
) -> dict[tuple[str, int], str]:
    """Slice each markdown file into the body under every indexed heading."""
    starts: dict[str, list[int]] = {}
    for node in nodes:
        if node.get("file_type") != "document" or node.get("node_kind") != "heading":
            continue
        location = str(node.get("source_location") or "").lstrip("L")
        if node.get("source_file") and location.isdigit():
            starts.setdefault(node["source_file"], []).append(int(location))

    sections: dict[tuple[str, int], str] = {}
    for source_file, heading_lines in starts.items():
        path = root / source_file
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        ordered = sorted(set(heading_lines))
        for index, start in enumerate(ordered):
            end = ordered[index + 1] - 1 if index + 1 < len(ordered) else len(lines)
            sections[(source_file, start)] = "\n".join(lines[start - 1 : end])
    return sections


def main() -> int:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    sections = read_sections(graph["nodes"])
    edges = bridge_edges(graph, sections)

    if not edges:
        print("no new spec->code edges; graph left untouched")
        return 0

    graph["links"].extend(edges)
    GRAPH.write_text(json.dumps(graph, indent=1), encoding="utf-8")
    headings = {e["source"] for e in edges}
    print(f"{len(edges)} spec->code edges from {len(headings)} document headings")
    print(f"graph.json now holds {len(graph['links'])} links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
