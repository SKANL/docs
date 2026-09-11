from pathlib import Path

import pytest

from docs.domain.transform import TransformSpec
from docs.infrastructure.transform import atomic_transform as atomic_transform_module
from docs.infrastructure.transform.atomic_transform import AtomicTransform


def test_atomic_transform_publishes_only_a_complete_scratch_output(tmp_path: Path):
    """Breaks if a partial scratch directory can be promoted."""
    output_dir = tmp_path / "output"
    spec = TransformSpec(output_dir=output_dir, expected_outputs=("report.txt", "manifest.json"))

    def build(_spec: TransformSpec, scratch: Path) -> None:
        (scratch / "report.txt").write_text("complete", encoding="utf-8")
        (scratch / "manifest.json").write_text('{"ok":true}', encoding="utf-8")

    result = AtomicTransform(build).transform(spec)

    assert result.output_dir == output_dir
    assert (output_dir / ".current").is_file()
    assert (result.outputs[0]).read_text(encoding="utf-8") == "complete"
    assert sorted(path.name for path in result.outputs) == ["manifest.json", "report.txt"]


def test_atomic_transform_keeps_the_previous_output_when_build_fails(tmp_path: Path):
    """Breaks if a producer error removes or replaces the last good output."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "report.txt").write_text("last known good", encoding="utf-8")
    spec = TransformSpec(output_dir=output_dir, expected_outputs=("report.txt",))

    def fail(_spec: TransformSpec, scratch: Path) -> None:
        (scratch / "report.txt").write_text("partial", encoding="utf-8")
        raise RuntimeError("renderer failed")

    with pytest.raises(RuntimeError, match="renderer failed"):
        AtomicTransform(fail).transform(spec)

    assert (output_dir / "report.txt").read_text(encoding="utf-8") == "last known good"


def test_atomic_transform_rejects_missing_declared_outputs_without_publishing(tmp_path: Path):
    """Breaks if an incomplete result replaces an earlier complete output."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "report.txt").write_text("last known good", encoding="utf-8")
    spec = TransformSpec(output_dir=output_dir, expected_outputs=("report.txt", "manifest.json"))

    def incomplete(_spec: TransformSpec, scratch: Path) -> None:
        (scratch / "report.txt").write_text("new report", encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing declared outputs: manifest\.json"):
        AtomicTransform(incomplete).transform(spec)

    assert (output_dir / "report.txt").read_text(encoding="utf-8") == "last known good"


def test_atomic_transform_preserves_the_current_output_when_pointer_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Breaks if a failed pointer swap makes the last complete output unreachable."""
    output_dir = tmp_path / "output"
    spec = TransformSpec(output_dir=output_dir, expected_outputs=("report.txt",))

    def build_old(_spec: TransformSpec, scratch: Path) -> None:
        (scratch / "report.txt").write_text("last known good", encoding="utf-8")

    previous = AtomicTransform(build_old).transform(spec)
    previous_pointer = (output_dir / ".current").read_text(encoding="utf-8")
    replace = atomic_transform_module.os.replace

    def fail_pointer_swap(source: str, destination: str) -> None:
        if Path(destination).name == ".current":
            raise OSError("simulated pointer publication failure")
        replace(source, destination)

    monkeypatch.setattr(atomic_transform_module.os, "replace", fail_pointer_swap)

    def build_new(_spec: TransformSpec, scratch: Path) -> None:
        (scratch / "report.txt").write_text("new output", encoding="utf-8")

    with pytest.raises(OSError, match="simulated pointer publication failure"):
        AtomicTransform(build_new).transform(spec)

    assert (previous.outputs[0]).read_text(encoding="utf-8") == "last known good"
    assert (output_dir / ".current").read_text(encoding="utf-8") == previous_pointer


def test_atomic_transform_rejects_a_file_as_the_output_target(tmp_path: Path):
    """Breaks if publication can overwrite a file where an output directory is required."""
    output_dir = tmp_path / "output"
    output_dir.write_text("not a directory", encoding="utf-8")
    spec = TransformSpec(output_dir=output_dir, expected_outputs=("report.txt",))

    with pytest.raises(ValueError, match="output_dir must be a directory"):
        AtomicTransform(lambda _spec, _scratch: None).transform(spec)

    assert output_dir.read_text(encoding="utf-8") == "not a directory"
