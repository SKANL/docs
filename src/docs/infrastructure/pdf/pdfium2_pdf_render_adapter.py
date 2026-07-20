from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops

_TRIM_PADDING = 18


def _parse_pages(spec: str, page_count: int) -> list[int]:
    """Expand a 1-based spec like "1-3,5" into ascending, de-duplicated
    0-based page indices bounded by `page_count`. Out-of-range pages are
    ignored so a stale spec never raises."""
    selected: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(n) for n in part.split("-", 1))
        else:
            start = end = int(part)
        for page in range(start, end + 1):
            if 1 <= page <= page_count:
                selected.add(page - 1)
    return sorted(selected)


def _autotrim(img: Image.Image) -> Image.Image:
    """Crop surrounding whitespace: diff against a white canvas, take the
    bounding box, and crop with a small padding. A blank page (no bbox) is
    returned unchanged."""
    rgb = img.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255)))
    bbox = diff.getbbox()
    if bbox is None:
        return img
    left = max(bbox[0] - _TRIM_PADDING, 0)
    top = max(bbox[1] - _TRIM_PADDING, 0)
    right = min(bbox[2] + _TRIM_PADDING, img.width)
    bottom = min(bbox[3] + _TRIM_PADDING, img.height)
    return img.crop((left, top, right, bottom))


class Pdfium2PdfRenderAdapter:
    """`PdfRenderPort` implementation using `pypdfium2` for rendering and
    `PIL` for the optional whitespace autotrim.

    Deterministic by construction: no timestamps or randomness, PNGs are
    written with stable `<pdf-stem>-p<NN>.png` names, so re-rendering the
    same PDF yields byte-identical output.
    """

    def render_pages(
        self,
        pdf_path: Path,
        out_dir: Path,
        dpi: int = 150,
        pages: str | None = None,
        autotrim: bool = True,
    ) -> list[Path]:
        pdf_path = Path(pdf_path)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        scale = dpi / 72

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            indices = _parse_pages(pages, len(pdf)) if pages else list(range(len(pdf)))
            written: list[Path] = []
            for index in indices:
                img = pdf[index].render(scale=scale).to_pil()
                if autotrim:
                    img = _autotrim(img)
                dest = out_dir / f"{pdf_path.stem}-p{index + 1:02d}.png"
                img.save(dest)
                written.append(dest)
            return written
        finally:
            pdf.close()
