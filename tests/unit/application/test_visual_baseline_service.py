from pathlib import Path

import pytest
from PIL import Image

from docs.application.visual_baseline import VisualBaselineError, VisualBaselineService


def _png(path: Path, color: str = "white") -> None:
    Image.new("RGB", (20, 20), color).save(path)


def test_baseline_update_is_explicit_and_deterministic(tmp_path: Path):
    source = tmp_path / "previews"
    source.mkdir()
    _png(source / "page-02.png")
    _png(source / "page-01.png")
    destination = tmp_path / "baseline"

    published = VisualBaselineService().update(source, destination)

    assert [path.name for path in published] == ["page-01.png", "page-02.png"]
    assert sorted(path.name for path in destination.iterdir()) == ["page-01.png", "page-02.png"]


def test_existing_baseline_requires_explicit_update_and_preserves_previous(tmp_path: Path):
    source = tmp_path / "previews"
    source.mkdir()
    _png(source / "page-01.png", "black")
    destination = tmp_path / "baseline"
    destination.mkdir()
    _png(destination / "page-01.png", "white")

    with pytest.raises(VisualBaselineError, match="--update"):
        VisualBaselineService().update(source, destination)
    with Image.open(destination / "page-01.png") as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_invalid_or_empty_previews_are_rejected_without_destination(tmp_path: Path):
    source = tmp_path / "previews"
    source.mkdir()
    destination = tmp_path / "baseline"
    with pytest.raises(VisualBaselineError, match="no PNG"):
        VisualBaselineService().update(source, destination)
    (source / "page-01.png").write_bytes(b"not png")
    with pytest.raises(VisualBaselineError, match="unreadable"):
        VisualBaselineService().update(source, destination)
    assert not destination.exists()
