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
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH = REPO_ROOT / "graphify-out" / "graph.json"

# A bare identifier only: anything with a dot, slash or space is a path, an
# attribute chain or a signature, and matching those invites false edges.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKTICKED = re.compile(r"`([^`\n]+)`")

# ponytail: short names like `path` or `name` collide across the tree and would
# bury real references in noise. Four characters is the cheap cutoff; tighten it
# only if a real symbol ever gets skipped. The boundary is pinned by a test so
# a change to this number cannot pass unnoticed.
MIN_SYMBOL_LENGTH = 4

# Written onto every edge this tool creates and read back to recognise its own
# output. One constant, because a typo across two literals would silently turn
# "already applied" into "nothing matched" and hide a bridge that had stopped
# working. `test_main_recognises_its_own_edges` proves the round trip.
BRIDGE_ORIGIN = "spec_code_bridge"


class GraphUnusable(RuntimeError):
    """The graph could not be read, or is not the shape this bridge expects."""


def normalize_symbol(label: str) -> str:
    """Strip call and attribute syntax off one label, returning the bare name.

    Handles the shapes graphify emits for code nodes -- `build()`,
    `._resolve()` -- and is applied to backticked spec text too, so both sides
    of a comparison are normalized the same way.
    """
    return label.strip().lstrip(".").removesuffix("()")


def backticked_symbols(text: str) -> set[str]:
    """Return the bare identifiers a document explicitly names in backticks.

    Only single-line spans match: the pattern forbids newlines, so a fenced
    block whose body sits on its own lines is never scanned. An inline span
    written *inside* a fence still matches -- the fence grants no exemption.
    Both behaviours are pinned by tests, because they fall out of the pattern
    rather than from a real markdown parser.
    """
    found = set()
    for raw in _BACKTICKED.findall(text):
        candidate = normalize_symbol(raw)
        if len(candidate) >= MIN_SYMBOL_LENGTH and _IDENTIFIER.match(candidate):
            found.add(candidate)
    return found


def resolve_within(root: Path, relative: str) -> Path | None:
    """Resolve `relative` under `root`, or return None when it escapes.

    `source_file` values arrive from graph.json, which an external tool
    regenerates. Joining them onto the repo root unchecked would let a
    `../../` entry reach any file this process can read.
    """
    try:
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None
    root_resolved = root.resolve()
    if candidate == root_resolved or root_resolved in candidate.parents:
        return candidate
    return None


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


def document_headings(nodes: list[dict]) -> list[dict]:
    """Return the markdown heading nodes this bridge attaches edges to."""
    return [
        n
        for n in nodes
        if n.get("file_type") == "document" and n.get("node_kind") == "heading"
    ]


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
    for node in document_headings(nodes):
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
                    "_origin": BRIDGE_ORIGIN,
                }
            )
    return edges


def read_sections(nodes: list[dict], root: Path) -> dict[tuple[str, int], str]:
    """Slice each markdown file into the body under every indexed heading.

    A heading's body runs to the line before the next indexed heading; the last
    heading in a file runs to end of file. A file the graph names but the tree
    does not hold is skipped rather than failing the run, because the graph can
    legitimately be one rebuild behind a deletion.
    """
    starts: dict[str, list[int]] = {}
    for node in document_headings(nodes):
        location = str(node.get("source_location") or "").lstrip("L")
        if node.get("source_file") and location.isdigit():
            starts.setdefault(node["source_file"], []).append(int(location))

    sections: dict[tuple[str, int], str] = {}
    for source_file, heading_lines in starts.items():
        path = resolve_within(root, source_file)
        if path is None or not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        ordered = sorted(set(heading_lines))
        for index, start in enumerate(ordered):
            end = ordered[index + 1] - 1 if index + 1 < len(ordered) else len(lines)
            sections[(source_file, start)] = "\n".join(lines[start - 1 : end])
    return sections


def load_graph(path: Path) -> dict:
    """Read graph.json, failing loudly on anything this bridge cannot use.

    A missing, unparseable or differently-shaped graph must never read as
    "nothing to link" -- that reports success while writing nothing, which is
    the failure mode most likely to go unnoticed for weeks.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GraphUnusable(
            f"cannot read {path}: {exc}. Build it with `graphify update .`"
        ) from exc
    try:
        graph = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GraphUnusable(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(graph, dict):
        raise GraphUnusable(f"{path} is not a node-link object")
    for key in ("nodes", "links"):
        if not isinstance(graph.get(key), list):
            raise GraphUnusable(
                f"{path} has no {key!r} list; graphify's schema changed and this "
                "bridge needs updating before its output can be trusted"
            )
    if not document_headings(graph["nodes"]):
        raise GraphUnusable(
            f"{path} holds no document heading nodes, so no spec could ever be "
            "linked; rebuild it with `graphify update .`"
        )
    return graph


def write_graph(graph: dict, path: Path) -> None:
    """Write the graph temp-then-rename so a crash cannot truncate it.

    graph.json is the only copy and is expensive to rebuild; an in-place write
    that died halfway would leave a half-written file behind.
    """
    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".graph-", suffix=".json"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(graph, stream, indent=1)
            stream.flush()
            # Rename is atomic, but without this the renamed file can still be
            # empty after a power loss -- the metadata lands before the bytes.
            os.fsync(stream.fileno())
        if path.exists():
            # mkstemp creates 0600; replacing without this would silently narrow
            # the permissions of a file other tools already read.
            os.chmod(temp_path, path.stat().st_mode & 0o777)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def main() -> int:
    # Read GRAPH and REPO_ROOT here rather than leaning on the callees' default
    # arguments: those bind once at import and would ignore any later override,
    # which is exactly what made these paths untestable before.
    try:
        graph = load_graph(GRAPH)
    except GraphUnusable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    headings = document_headings(graph["nodes"])
    sections = read_sections(headings, REPO_ROOT)
    named = {n["source_file"] for n in headings if n.get("source_file")}
    reached = {source_file for source_file, _ in sections}
    if missing := sorted(named - reached):
        # Skipping is correct -- the graph can lag a deletion -- but silence
        # would hide a wholesale path mismatch behind "nothing matched".
        print(f"note: {len(missing)} file(s) named by the graph were unreadable")

    edges = bridge_edges(graph, sections)
    if not edges:
        already = sum(
            1 for link in graph["links"] if link.get("_origin") == BRIDGE_ORIGIN
        )
        if already:
            print(f"no new edges; {already} bridge edges already present")
        else:
            print("no spec->code edges matched; graph left untouched")
        return 0

    graph["links"].extend(edges)
    try:
        write_graph(graph, GRAPH)
    except OSError as exc:
        print(f"error: could not write {GRAPH}: {exc}", file=sys.stderr)
        return 1
    linked = {e["source"] for e in edges}
    print(f"{len(edges)} spec->code edges from {len(linked)} document headings")
    print(f"graph.json now holds {len(graph['links'])} links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
