import importlib
import tomllib
from pathlib import Path

import pytest

from docs.domain.workspace_format import WorkspaceFormatError, write_workspace_marker
from docs.local_worker import main


def test_local_worker_rejects_missing_marker_before_creating_state(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceFormatError, match="workspace_marker_missing"):
        main(["--workspace-root", str(tmp_path)])

    assert list(tmp_path.iterdir()) == []


def test_local_worker_rejects_unsupported_marker_before_creating_state(tmp_path: Path) -> None:
    (tmp_path / "workspace.json").write_text(
        '{"schema":"docs.workspace/v2"}', encoding="utf-8"
    )

    with pytest.raises(WorkspaceFormatError, match="workspace_schema_unsupported"):
        main(["--workspace-root", str(tmp_path)])

    assert [path.name for path in tmp_path.iterdir()] == ["workspace.json"]


def test_local_worker_builds_and_runs_for_a_canonical_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_workspace_marker(tmp_path)
    calls: list[int] = []

    class Runner:
        def run_until_stopped(self, iterations: int) -> None:
            calls.append(iterations)

    monkeypatch.setattr("docs.local_worker._build_worker", lambda *args: Runner())

    assert main(["--workspace-root", str(tmp_path), "--iterations", "2"]) == 0
    assert calls == [2]
    assert (tmp_path / ".docs" / "x20.sqlite3").is_file()


def _declared_docs_worker_target() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return metadata["project"]["scripts"]["docs-worker"]


def test_packaged_docs_worker_targets_local_worker() -> None:
    assert _declared_docs_worker_target() == "docs.local_worker:main"


def test_declared_entry_point_dispatches_to_local_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str] | None] = []

    def fake_main(argv: list[str] | None = None) -> int:
        calls.append(argv)
        return 17

    monkeypatch.setattr("docs.local_worker.main", fake_main)
    module_name, separator, callable_name = _declared_docs_worker_target().partition(":")
    assert separator == ":"

    entry_point = getattr(importlib.import_module(module_name), callable_name)
    assert entry_point(["--workspace-root", "example-workspace"]) == 17
    assert calls == [["--workspace-root", "example-workspace"]]
