"""Validate that traceability evidence resolves to collected pytest tests.

The validator deliberately answers one mechanical question: does every JSON
field named ``test`` point to a real, collected pytest node?  Whether the
referenced assertions support the surrounding prose remains a human review
responsibility.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath

_TEST_NODE = re.compile(r"^(tests/(?:[^/]+/)*test_[^/]+\.py)::(test_[^:\[\]]+)$")


class TraceabilityCollectionError(RuntimeError):
    """Pytest could not collect the requested evidence files."""


def _test_fields(value: object, location: str = "$") -> Iterator[tuple[str, object]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key == "test":
                yield child_location, child
            yield from _test_fields(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _test_fields(child, f"{location}[{index}]")


def _normalize_collected_nodeid(nodeid: str) -> str:
    normalized = nodeid.strip().replace("\\", "/")
    if "::" not in normalized:
        return normalized
    file_name, test_name = normalized.split("::", maxsplit=1)
    return f"{file_name}::{test_name.split('[', maxsplit=1)[0]}"


def _parse_evidence(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value:
        return None
    match = _TEST_NODE.fullmatch(value)
    if match is None:
        return None
    file_name, test_name = match.groups()
    path = PurePosixPath(file_name)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    return file_name, test_name


def _defined_test_functions(path: Path) -> frozenset[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return frozenset()
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    )


def collect_test_nodeids(repo_root: Path, test_files: Collection[Path]) -> frozenset[str]:
    """Collect and normalize pytest node IDs from only ``test_files``."""
    root = repo_root.resolve()
    relative_files: list[str] = []
    for path in sorted({item.resolve() for item in test_files}, key=lambda item: item.as_posix()):
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise TraceabilityCollectionError(f"test file escapes repository root: {path}") from exc
        relative_files.append(relative.as_posix())
    if not relative_files:
        return frozenset()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *relative_files],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise TraceabilityCollectionError(f"pytest collection failed ({result.returncode}): {detail}")
    return frozenset(
        _normalize_collected_nodeid(line)
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    )


def validate_traceability(
    payload: Mapping[str, object],
    repo_root: Path,
    collected_nodeids: Collection[str],
) -> tuple[str, ...]:
    """Return deterministic errors for malformed or unresolved test evidence."""
    errors: list[str] = []
    evidence = list(_test_fields(payload))
    if not evidence:
        errors.append("traceability contains no test evidence")

    normalized_collected = {_normalize_collected_nodeid(nodeid) for nodeid in collected_nodeids}
    parsed: list[tuple[str, str, str]] = []
    for location, value in evidence:
        if not isinstance(value, str) or not value:
            errors.append(f"{location}: test evidence must be a non-empty string")
            continue
        resolved = _parse_evidence(value)
        if resolved is None:
            errors.append(
                f"{location}: invalid test evidence {value!r}; expected repository-relative "
                "tests/**/*.py::test_name"
            )
            continue
        file_name, test_name = resolved
        parsed.append((location, file_name, test_name))

    counts = Counter(f"{file_name}::{test_name}" for _, file_name, test_name in parsed)
    for nodeid, count in sorted(counts.items()):
        if count > 1:
            errors.append(f"duplicate test evidence: {nodeid} ({count} references)")

    root = repo_root.resolve()
    definitions: dict[str, frozenset[str]] = {}
    for location, file_name, test_name in parsed:
        file_path = root / PurePosixPath(file_name)
        if not file_path.is_file():
            errors.append(f"{location}: missing test file: {file_name}")
            continue
        definitions.setdefault(file_name, _defined_test_functions(file_path))
        if test_name not in definitions[file_name]:
            errors.append(f"{location}: missing test function: {file_name}::{test_name}")
            continue
        nodeid = f"{file_name}::{test_name}"
        if nodeid not in normalized_collected:
            errors.append(f"{location}: test is not collected by pytest: {nodeid}")

    return tuple(sorted(errors))


def _safe_existing_test_files(payload: Mapping[str, object], repo_root: Path) -> frozenset[Path]:
    files: set[Path] = set()
    for _, value in _test_fields(payload):
        parsed = _parse_evidence(value)
        if parsed is None:
            continue
        path = repo_root / PurePosixPath(parsed[0])
        if path.is_file():
            files.add(path)
    return frozenset(files)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("traceability", nargs="?", default="docs/traceability.json", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    traceability = args.traceability if args.traceability.is_absolute() else repo_root / args.traceability
    try:
        payload = json.loads(traceability.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read traceability JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("error: traceability root must be a JSON object", file=sys.stderr)
        return 1
    try:
        collected = collect_test_nodeids(repo_root, _safe_existing_test_files(payload, repo_root))
    except TraceabilityCollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = validate_traceability(payload, repo_root, collected)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"traceability valid: {sum(1 for _ in _test_fields(payload))} referenced test node(s) resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
