from pathlib import Path

from PIL import Image, ImageDraw

from docs.domain.visual_baseline import compare_preview_baseline


def _page(path: Path, x: int) -> None:
    image = Image.new("RGB", (120, 160), "white")
    ImageDraw.Draw(image).rectangle((x, 20, x + 20, 80), fill="black")
    image.save(path)


def test_visual_baseline_reports_page_similarity_and_missing_pages(tmp_path: Path):
    actual = tmp_path / "actual"
    baseline = tmp_path / "baseline"
    actual.mkdir()
    baseline.mkdir()
    _page(actual / "page-01.png", 10)
    _page(baseline / "page-01.png", 10)

    findings = compare_preview_baseline(actual, baseline, minimum_similarity=0.9)

    assert findings == []

    (baseline / "page-01.png").unlink()
    findings = compare_preview_baseline(actual, baseline, minimum_similarity=0.9)

    assert findings[0].code == "visual.baseline_missing"
    assert findings[0].page == 1


def test_visual_baseline_reports_layout_change(tmp_path: Path):
    actual = tmp_path / "actual"
    baseline = tmp_path / "baseline"
    actual.mkdir()
    baseline.mkdir()
    _page(actual / "page-01.png", 90)
    _page(baseline / "page-01.png", 10)

    findings = compare_preview_baseline(actual, baseline, minimum_similarity=0.99)

    assert findings[0].code == "visual.baseline_changed"
    assert findings[0].page == 1
    assert findings[0].similarity is not None
