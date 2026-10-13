"""Several registry instances share one file inside the sidecar (one per composition)."""

import threading

import pytest

from docs.application.workspaces import WorkspaceRegistry


def test_concurrent_instances_on_one_registry_file_never_fail(tmp_path):
    path = tmp_path / ".docs" / "workspaces.json"
    writer, reader = WorkspaceRegistry(path), WorkspaceRegistry(path)
    workspace = writer.create("Concurrent", tmp_path / "ws")
    errors: list[BaseException] = []
    stop = threading.Event()

    def read_forever() -> None:
        while not stop.is_set():
            try:
                reader.list()
            except BaseException as exc:
                errors.append(exc)

    threads = [threading.Thread(target=read_forever) for _ in range(3)]
    for thread in threads:
        thread.start()
    try:
        for index in range(150):
            try:
                WorkspaceRegistry(path).rename(workspace["id"], f"Concurrent {index}")
            except BaseException as exc:
                errors.append(exc)
    finally:
        stop.set()
        for thread in threads:
            thread.join()
    assert errors == []
    assert WorkspaceRegistry(path).get(workspace["id"])["name"] == "Concurrent 149"


def test_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / ".docs" / "workspaces.json"
    registry = WorkspaceRegistry(path)
    registry.create("Original", tmp_path / "ws")

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("docs.application.workspaces.json.dumps", explode)
    with pytest.raises(OSError, match="disk full"):
        registry.create("Second", tmp_path / "ws2")
    assert sorted(p.name for p in path.parent.iterdir()) == ["workspaces.json"]
