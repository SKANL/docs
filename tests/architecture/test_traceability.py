from __future__ import annotations

import json
from pathlib import Path

import pytest
from validate_traceability import (
    TraceabilityCollectionError,
    collect_test_nodeids,
    main,
    validate_traceability,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _payload(nodeid: object) -> dict[str, object]:
    return {"evidence": {"test": nodeid}}


def _write_test(repo_root: Path, body: str = "def test_present():\n    assert True\n") -> Path:
    path = repo_root / "tests" / "unit" / "test_sample.py"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_is_reported(tmp_path: Path) -> None:
    errors = validate_traceability(
        _payload("tests/unit/test_missing.py::test_present"),
        tmp_path,
        frozenset(),
    )

    assert errors == ("$.evidence.test: missing test file: tests/unit/test_missing.py",)


def test_missing_test_function_is_reported(tmp_path: Path) -> None:
    _write_test(tmp_path)

    errors = validate_traceability(
        _payload("tests/unit/test_sample.py::test_absent"),
        tmp_path,
        frozenset(),
    )

    assert errors == ("$.evidence.test: missing test function: tests/unit/test_sample.py::test_absent",)


def test_defined_but_non_collected_test_is_reported(tmp_path: Path) -> None:
    _write_test(tmp_path)

    errors = validate_traceability(
        _payload("tests/unit/test_sample.py::test_present"),
        tmp_path,
        frozenset(),
    )

    assert errors == ("$.evidence.test: test is not collected by pytest: tests/unit/test_sample.py::test_present",)


def test_parameterized_collected_nodeids_are_normalized_to_the_base_test(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "import pytest\n\n@pytest.mark.parametrize('value', [1, 2])\ndef test_present(value):\n    assert value\n",
    )
    nodeids = collect_test_nodeids(tmp_path, [tmp_path / "tests" / "unit" / "test_sample.py"])

    assert nodeids == frozenset({"tests/unit/test_sample.py::test_present"})
    assert validate_traceability(_payload("tests/unit/test_sample.py::test_present"), tmp_path, nodeids) == ()


def test_traversal_and_absolute_test_evidence_are_rejected(tmp_path: Path) -> None:
    payload = {
        "traversal": {"test": "tests/../outside/test_escape.py::test_escape"},
        "absolute": {"test": "/tests/unit/test_sample.py::test_present"},
    }

    errors = validate_traceability(payload, tmp_path, frozenset())

    assert errors == (
        (
            "$.absolute.test: invalid test evidence '/tests/unit/test_sample.py::test_present'; expected "
            "repository-relative tests/**/*.py::test_name"
        ),
        (
            "$.traversal.test: invalid test evidence 'tests/../outside/test_escape.py::test_escape'; expected "
            "repository-relative tests/**/*.py::test_name"
        ),
    )


def test_duplicate_and_empty_test_evidence_are_rejected(tmp_path: Path) -> None:
    _write_test(tmp_path)
    nodeid = "tests/unit/test_sample.py::test_present"
    payload = {"first": {"test": nodeid}, "second": [{"test": nodeid}], "empty": {"test": ""}}

    errors = validate_traceability(payload, tmp_path, {nodeid})

    assert errors == (
        "$.empty.test: test evidence must be a non-empty string",
        "duplicate test evidence: tests/unit/test_sample.py::test_present (2 references)",
    )


def test_empty_traceability_is_rejected(tmp_path: Path) -> None:
    assert validate_traceability({}, tmp_path, frozenset()) == ("traceability contains no test evidence",)


def test_collection_failure_is_not_silently_treated_as_no_tests(tmp_path: Path) -> None:
    path = _write_test(tmp_path, "def test_broken(:\n")

    with pytest.raises(TraceabilityCollectionError, match="pytest collection failed"):
        collect_test_nodeids(tmp_path, [path])


def test_entry_point_returns_nonzero_for_unresolved_evidence(tmp_path: Path) -> None:
    traceability = tmp_path / "traceability.json"
    traceability.write_text(
        json.dumps(_payload("tests/unit/test_missing.py::test_present")),
        encoding="utf-8",
    )

    assert main([str(traceability), "--repo-root", str(tmp_path)]) == 1


def test_real_traceability_references_only_collected_tests() -> None:
    payload = json.loads((REPO_ROOT / "docs" / "traceability.json").read_text(encoding="utf-8"))
    references: set[Path] = set()

    def gather(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "test" and isinstance(child, str) and "::" in child:
                    references.add(REPO_ROOT / child.split("::", maxsplit=1)[0])
                gather(child)
        elif isinstance(value, list):
            for child in value:
                gather(child)

    gather(payload)
    collected = collect_test_nodeids(REPO_ROOT, references)

    assert validate_traceability(payload, REPO_ROOT, collected) == ()
