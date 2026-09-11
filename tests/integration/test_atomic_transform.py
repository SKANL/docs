from pathlib import Path

import pytest

from docs.domain.transform import TransformSpec
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
    assert (output_dir / "report.txt").read_text(encoding="utf-8") == "complete"
    assert sorted(path.relative_to(output_dir).as_posix() for path in result.outputs) == ["manifest.json", "report.txt"]


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
