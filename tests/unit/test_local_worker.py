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
