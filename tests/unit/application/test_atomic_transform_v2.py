import json
from pathlib import Path

import pytest

import docs.infrastructure.transform.v2_atomic_transform as atomic_module
from docs.application.atomic_transform_v2 import AtomicTransform, TransformResult, TransformSpec


def test_callable_transform_publishes_non_empty_outputs_and_cleans_scratch(tmp_path: Path) -> None:
    destination = tmp_path / "public"
    scratch_seen: list[Path] = []
    spec = TransformSpec(
        expected_outputs=("body.txt",),
        destinations=(destination / "body.txt",),
    )

    def build(scratch: Path) -> None:
        scratch_seen.append(scratch)
        (scratch / "body.txt").write_text("new", encoding="utf-8")

    result = AtomicTransform().run(spec, build)

    assert result == TransformResult(ok=True, outputs=(destination / "body.txt",))
    assert (destination / "body.txt").read_text(encoding="utf-8") == "new"
    assert not scratch_seen[0].exists()


def test_command_uses_injected_subprocess_adapter(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []
    destination = tmp_path / "result.txt"
    spec = TransformSpec(expected_outputs=("result.txt",), destinations=(destination,), command=("tool", "--out"))

    def adapter(command: tuple[str, ...], *, cwd: Path, **_kwargs) -> None:
        calls.append((command, cwd))
        (cwd / "result.txt").write_text("command output", encoding="utf-8")

    result = AtomicTransform(subprocess_adapter=adapter).run(spec)

    assert result.ok is True
    assert calls == [(('tool', '--out'), calls[0][1])]
    assert destination.read_text(encoding="utf-8") == "command output"


def test_failed_transform_preserves_all_previous_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "nested" / "second.txt"
    second.parent.mkdir()
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second"), destinations=(first, second))

    def build(scratch: Path) -> None:
        (scratch / "first").write_text("new-first", encoding="utf-8")
        (scratch / "second").write_text("new-second", encoding="utf-8")

    real_replace = atomic_module.os.replace
    injected = False

    def replace(source: str | Path, target: str | Path) -> None:
        nonlocal injected
        if Path(target) == second and not injected and Path(source).name == "second":
            injected = True
            raise OSError("injected publish failure")
        real_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", replace)
    result = AtomicTransform().run(spec, build)

    assert result.ok is False
    assert first.read_text(encoding="utf-8") == "old-first"
    assert second.read_text(encoding="utf-8") == "old-second"


def test_missing_or_empty_expected_output_is_failure_with_optional_warning(tmp_path: Path) -> None:
    destination = tmp_path / "out.txt"
    spec = TransformSpec(
        expected_outputs=("out.txt",),
        destinations=(destination,),
        warn_on_failure=True,
    )

    result = AtomicTransform().run(spec, lambda scratch: (scratch / "out.txt").touch())

    assert result.ok is False
    assert result.outputs == ()
    assert result.warnings == ("atomic transform failed: expected output 'out.txt' is missing or empty",)
    assert not destination.exists()


@pytest.mark.parametrize(
    "spec",
    [
        TransformSpec(expected_outputs=(), destinations=()),
        TransformSpec(expected_outputs=("../escape",), destinations=(Path("out"),)),
        TransformSpec(expected_outputs=("out",), destinations=()),
    ],
)
def test_spec_validation_rejects_unsafe_or_mismatched_inputs(spec: TransformSpec) -> None:
    with pytest.raises(ValueError):
        AtomicTransform().run(spec, lambda _scratch: None)


def test_command_timeout_and_stderr_are_reported_by_the_adapter_boundary(tmp_path: Path) -> None:
    destination = tmp_path / "result.txt"
    spec = TransformSpec(
        expected_outputs=("result.txt",),
        destinations=(destination,),
        command=("tool",),
        timeout_seconds=12,
    )
    calls: list[dict[str, object]] = []

    def adapter(command, *, cwd, timeout, text, capture_output):
        calls.append({"command": command, "cwd": cwd, "timeout": timeout, "text": text, "capture_output": capture_output})
        return type("Result", (), {"returncode": 9, "stderr": "missing font"})()

    result = AtomicTransform(subprocess_adapter=adapter).run(spec)

    assert result.ok is False
    assert result.error == "command exited with status 9; stderr: missing font"
    assert calls[0]["timeout"] == 12
    assert calls[0]["capture_output"] is True


def test_cleanup_failure_is_reported_instead_of_silently_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "result.txt"
    spec = TransformSpec(expected_outputs=("result.txt",), destinations=(destination,))

    original_cleanup = atomic_module.shutil.rmtree

    def cleanup(path: Path, *args, **kwargs) -> None:
        if path.name.startswith(".atomic-transform-"):
            raise OSError("cleanup denied")
        original_cleanup(path, *args, **kwargs)

    monkeypatch.setattr(atomic_module.shutil, "rmtree", cleanup)
    result = AtomicTransform().run(spec, lambda scratch: (scratch / "result.txt").write_text("ok", encoding="utf-8"))

    assert result.ok is True
    assert result.warnings == ("atomic transform cleanup failed: cleanup denied",)


def test_command_uses_a_bounded_default_timeout_and_reports_both_output_streams(tmp_path: Path) -> None:
    destination = tmp_path / "result.txt"
    spec = TransformSpec(expected_outputs=("result.txt",), destinations=(destination,), command=("tool",))
    calls: list[dict[str, object]] = []

    def adapter(command, *, cwd, timeout, text, capture_output):
        calls.append({"command": command, "cwd": cwd, "timeout": timeout, "text": text, "capture_output": capture_output})
        return type("Result", (), {"returncode": 9, "stderr": "missing font", "stdout": "render started"})()

    result = AtomicTransform(subprocess_adapter=adapter).run(spec)

    assert calls[0]["timeout"] == 60
    assert result.error == "command exited with status 9; stdout: render started; stderr: missing font"


def test_publish_failure_continues_rollback_after_one_destination_recovery_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    third = tmp_path / "third.txt"
    for destination in (first, second, third):
        destination.write_text(f"old-{destination.stem}", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second", "third"), destinations=(first, second, third))

    def build(scratch: Path) -> None:
        for output in spec.expected_outputs:
            (scratch / output).write_text(f"new-{output}", encoding="utf-8")

    real_replace = atomic_module.os.replace
    failed_publish = False
    failed_restore = False

    def replace(source: str | Path, target: str | Path) -> None:
        nonlocal failed_publish, failed_restore
        if Path(source).name == "third" and Path(target) == third and not failed_publish:
            failed_publish = True
            raise OSError("publish denied")
        if Path(source).name == "1" and Path(target) == second and failed_publish and not failed_restore:
            failed_restore = True
            raise OSError("second restore denied")
        real_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", replace)
    result = AtomicTransform().run(spec, build)

    assert result.ok is False
    assert "publish denied" in result.error
    assert "second restore denied" in result.error
    assert first.read_text(encoding="utf-8") == "old-first"


def test_backup_cleanup_failure_does_not_report_a_committed_publication_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "result.txt"
    destination.write_text("old", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("result.txt",), destinations=(destination,))
    original_unlink = Path.unlink

    def unlink(path: Path, *args, **kwargs) -> None:
        if path.parent.name == ".backups":
            raise OSError("backup cleanup denied")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    result = AtomicTransform().run(spec, lambda scratch: (scratch / "result.txt").write_text("new", encoding="utf-8"))

    assert result.ok is True
    assert destination.read_text(encoding="utf-8") == "new"


def test_multi_output_publication_recovers_after_process_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second"), destinations=(first, second))

    def build(scratch: Path) -> None:
        (scratch / "first").write_text("new-first", encoding="utf-8")
        (scratch / "second").write_text("new-second", encoding="utf-8")

    real_replace = atomic_module.os.replace
    interrupted = False

    def replace(source: str | Path, target: str | Path) -> None:
        nonlocal interrupted
        if Path(target) == second and not interrupted and Path(source).name == "second":
            interrupted = True
            raise KeyboardInterrupt("simulated process interruption")
        real_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", replace)
    with pytest.raises(KeyboardInterrupt):
        AtomicTransform().run(spec, build)

    monkeypatch.setattr(atomic_module.os, "replace", real_replace)
    def rebuild(scratch: Path) -> None:
        (scratch / "first").write_text("final-first", encoding="utf-8")
        (scratch / "second").write_text("final-second", encoding="utf-8")

    result = AtomicTransform().run(spec, rebuild)

    assert result.ok is True
    assert first.read_text(encoding="utf-8") == "final-first"
    assert second.read_text(encoding="utf-8") == "final-second"


def test_cross_device_publication_is_rejected_before_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "published" / "result.txt"
    destination.parent.mkdir()
    destination.write_text("old", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("result",), destinations=(destination,))
    real_stat = atomic_module.os.stat
    replace_calls = 0

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if not kwargs and Path(path) == destination.parent:
            class DifferentDevice:
                st_dev = result.st_dev + 1

            return DifferentDevice()
        return result

    def fail_replace(*_args, **_kwargs):
        nonlocal replace_calls
        replace_calls += 1
        raise AssertionError("replacement must not start")

    monkeypatch.setattr(atomic_module.os, "stat", fake_stat)
    monkeypatch.setattr(atomic_module.os, "replace", fail_replace)

    result = AtomicTransform().run(
        spec, lambda scratch: (scratch / "result").write_text("new", encoding="utf-8")
    )

    assert result.ok is False
    assert "device" in (result.error or "").lower()
    assert replace_calls == 0
    assert destination.read_text(encoding="utf-8") == "old"


def test_prepared_recovery_restores_destination_even_when_it_matches_expected_hash(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second"), destinations=(first, second))

    def build(scratch: Path) -> None:
        (scratch / "first").write_text("new-first", encoding="utf-8")
        (scratch / "second").write_text("new-second", encoding="utf-8")

    real_replace = atomic_module.os.replace
    interrupted = False

    def interrupt_after_first(source: str | Path, target: str | Path) -> None:
        nonlocal interrupted
        real_replace(source, target)
        if Path(target) == first and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(atomic_module.os, "replace", interrupt_after_first)
    with pytest.raises(KeyboardInterrupt):
        AtomicTransform().run(spec, build)
    monkeypatch.undo()

    AtomicTransform._recover_pending(spec.destinations)

    assert first.read_text(encoding="utf-8") == "old-first"
    assert second.read_text(encoding="utf-8") == "old-second"


def test_publication_rejects_parent_that_becomes_symlink_before_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "published" / "result.txt"
    destination.parent.mkdir()
    destination.write_text("old", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("result",), destinations=(destination,))
    moved = tmp_path / "moved"
    destination.parent.rename(moved)
    destination.parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        AtomicTransform().run(
            spec, lambda scratch: (scratch / "result").write_text("new", encoding="utf-8")
        )


def test_recovery_failure_keeps_journal_and_backups_for_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second"), destinations=(first, second))

    def build(scratch: Path) -> None:
        (scratch / "first").write_text("new-first", encoding="utf-8")
        (scratch / "second").write_text("new-second", encoding="utf-8")

    real_replace = atomic_module.os.replace
    interrupted = False

    def replace(source: str | Path, target: str | Path) -> None:
        nonlocal interrupted
        if Path(target) == second and not interrupted and Path(source).name == "second":
            interrupted = True
            raise KeyboardInterrupt("simulated process interruption")
        real_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", replace)
    with pytest.raises(KeyboardInterrupt):
        AtomicTransform().run(spec, build)
    journal = tmp_path / ".atomic-transform-journal.json"
    assert journal.exists()
    backup_dir = Path(json.loads(journal.read_text(encoding="utf-8"))["backup_dir"])
    assert backup_dir.exists()

    def fail_recovery(*_args, **_kwargs):
        raise OSError("recovery temporarily unavailable")

    monkeypatch.setattr(atomic_module.os, "replace", fail_recovery)
    with pytest.raises(RuntimeError, match="recovery temporarily unavailable"):
        atomic_module.AtomicTransform._recover_pending(spec.destinations)
    assert journal.exists()
    assert backup_dir.exists()


def test_multi_output_cleanup_crash_leaves_committed_journal_for_safe_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_text("old-first", encoding="utf-8")
    second.write_text("old-second", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("first", "second"), destinations=(first, second))
    real_rmtree = atomic_module.shutil.rmtree
    crashed = False

    def crash_cleanup(path, *args, **kwargs):
        nonlocal crashed
        if Path(path).name.startswith(".atomic-transform-backups-") and not crashed:
            crashed = True
            raise OSError("cleanup crash")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(atomic_module.shutil, "rmtree", crash_cleanup)
    result = AtomicTransform().run(spec, lambda scratch: [(scratch / name).write_text(f"new-{name}", encoding="utf-8") for name in ("first", "second")])
    assert result.ok is True
    assert (first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8")) == ("new-first", "new-second")

    monkeypatch.setattr(atomic_module.shutil, "rmtree", real_rmtree)
    AtomicTransform().run(spec, lambda scratch: [(scratch / name).write_text(f"newer-{name}", encoding="utf-8") for name in ("first", "second")])
    assert (first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8")) == ("newer-first", "newer-second")


def test_single_output_interruption_is_recoverable_on_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "result.txt"
    destination.write_text("old", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("result",), destinations=(destination,))
    real_replace = atomic_module.os.replace
    interrupted = False

    def interrupt(source, target):
        nonlocal interrupted
        if Path(target) == destination and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("crash")
        real_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        AtomicTransform().run(spec, lambda scratch: (scratch / "result").write_text("new", encoding="utf-8"))
    monkeypatch.setattr(atomic_module.os, "replace", real_replace)
    result = AtomicTransform().run(spec, lambda scratch: (scratch / "result").write_text("final", encoding="utf-8"))
    assert result.ok is True
    assert destination.read_text(encoding="utf-8") == "final"


def test_recovery_rejects_journal_paths_outside_intended_roots(tmp_path: Path):
    destination = tmp_path / "output" / "result.txt"
    journal = destination.parent / ".atomic-transform-journal.json"
    backup_dir = destination.parent / ".atomic-transform-backups-test"
    backup_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch", encoding="utf-8")
    journal.write_text(json.dumps({
        "state": "prepared",
        "backup_dir": str(backup_dir),
        "entries": [{"target": str(outside), "backup": str(backup_dir / "0"), "existed": True}],
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside intended"):
        atomic_module.AtomicTransform._recover_pending((destination,))

    assert outside.read_text(encoding="utf-8") == "do not touch"


def test_committed_journal_write_failure_does_not_roll_back_published_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    destination = tmp_path / "result.txt"
    destination.write_text("old", encoding="utf-8")
    spec = TransformSpec(expected_outputs=("result",), destinations=(destination,))
    real_write = atomic_module.AtomicTransform._write_journal
    calls = 0

    def fail_committed(path, payload):
        nonlocal calls
        calls += 1
        if payload.get("state") == "committed":
            raise OSError("journal commit unavailable")
        return real_write(path, payload)

    monkeypatch.setattr(atomic_module.AtomicTransform, "_write_journal", fail_committed)
    result = atomic_module.AtomicTransform().run(
        spec, lambda scratch: (scratch / "result").write_text("new", encoding="utf-8")
    )
    assert calls == 2
    assert result.ok is True
    assert result.error is None
    assert result.warnings == (
        "atomic transform journal commit failed after publication: journal commit unavailable",
    )
    assert destination.read_text(encoding="utf-8") == "new"

    monkeypatch.setattr(atomic_module.AtomicTransform, "_write_journal", real_write)
    atomic_module.AtomicTransform._recover_pending(spec.destinations)
    assert destination.read_text(encoding="utf-8") == "old"


def test_transform_rejects_symlinked_publication_destination(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    destination = tmp_path / "result.txt"
    try:
        destination.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    spec = TransformSpec(expected_outputs=("result",), destinations=(destination,))

    with pytest.raises(ValueError, match="symlink"):
        AtomicTransform().run(
            spec, lambda scratch: (scratch / "result").write_text("new", encoding="utf-8")
        )

    assert outside.read_text(encoding="utf-8") == "outside"
