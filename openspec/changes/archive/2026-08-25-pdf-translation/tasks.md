# PDF Translation Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use `- [ ]` for tracking.
> Strict TDD: the failing test is written and *seen to fail* before implementation.

**Goal:** `docs translate <input.pdf> --to <lang>` produces a translated PDF with
the original layout preserved, byte-identical across reruns, that never refuses.

**Architecture:** Extract text objects with `pypdfium2`, group them into blocks by
geometry, translate each block through a cached `TranslationPort`, then remove and
re-lay the block's objects inside their original bounding box. See `design.md`.

**Tech Stack:** `pypdfium2` (already declared), `pdf-inspector` (MIT, new), Pillow
(already declared), Typer, pytest.

**Spec:** `openspec/changes/pdf-translation/design.md` — read the 8 ADRs first.
ADR-1 and ADR-3 each describe a bug that ships silently if ignored.

## Global Constraints

- Dependency direction: `cli -> application -> domain`; infrastructure implements
  domain ports. Never import infrastructure from domain or application.
- Adapters are wired only in the composition root, `src/docs/cli/_shared.py`.
- CLI user-facing strings are **Spanish**; code, comments and docs are **English**.
- Determinism: same inputs MUST produce byte-identical outputs. No timestamps,
  no randomness.
- `filterwarnings = ["error"]` is active. A warning fails the suite.
- Deliberate simplifications carry a `# ponytail:` comment naming the ceiling
  and the upgrade path.
- Every new config key must be added to `src/docs/domain/config_vocabulary.py`
  or `tests/architecture/test_config_vocabulary.py` fails.
- Run `uv run pytest`, `uv run ruff check .` and `uv run mypy` before each commit.

---

## Task 1: Deterministic PDF `/ID` normalization

The foundation. Without this every byte-identity test in this change is flaky,
and the flake is a real product bug. See ADR-3.

**Files:**
- Create: `src/docs/domain/pdf_id.py`
- Test: `tests/unit/domain/test_pdf_id.py`

**Interfaces:**
- Produces: `normalize_pdf_id(raw: bytes) -> bytes`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_pdf_id.py
import hashlib

from docs.domain.pdf_id import normalize_pdf_id

TRAILER = b"trailer\r\n<</Info 33 0 R /Root 1 0 R /Size 38/ID[<%s><%s>]>>\r\n"


def _pdf(id_a: bytes, id_b: bytes, body: bytes = b"body bytes here") -> bytes:
    return b"%PDF-1.4\r\n" + body + b"\r\n" + TRAILER % (id_a, id_b)


def test_same_content_different_random_ids_normalizes_identical():
    a = _pdf(b"DF3B541ACE3E866AAB616FC3D178BA13", b"DF3B541ACE3E866AAB616FC3D178BA13")
    b = _pdf(b"53825174AA5D8408921C42C74CBF5F24", b"53825174AA5D8408921C42C74CBF5F24")
    assert hashlib.sha256(normalize_pdf_id(a)).digest() == hashlib.sha256(normalize_pdf_id(b)).digest()


def test_byte_length_is_preserved_so_xref_offsets_stay_valid():
    raw = _pdf(b"A" * 32, b"B" * 32)
    assert len(normalize_pdf_id(raw)) == len(raw)


def test_different_content_yields_different_id():
    a = normalize_pdf_id(_pdf(b"A" * 32, b"A" * 32))
    b = normalize_pdf_id(_pdf(b"A" * 32, b"A" * 32, body=b"DIFFERENT body"))
    assert a != b


def test_pdf_without_id_array_is_returned_unchanged():
    raw = b"%PDF-1.4\r\nno trailer id here\r\n"
    assert normalize_pdf_id(raw) == raw
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/domain/test_pdf_id.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docs.domain.pdf_id'`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/pdf_id.py
"""Deterministic PDF file-identifier normalization.

PDFium writes a RANDOM `/ID` into the trailer on every save, so two runs over
identical input differ in exactly those bytes and nowhere else (measured: same
1758-byte file, first difference at offset 1662, only the trailer /ID array).
This is the PDF analogue of the `.docx` zip-timestamp problem: a "flaky"
byte-identity test here is a product bug, not test noise.

The replacement is the same LENGTH as what it replaces, so every xref byte
offset in the file stays valid and the document still opens.

Pure data. No I/O, no imports from other layers.
"""
from __future__ import annotations

import hashlib
import re

_ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]")


def normalize_pdf_id(raw: bytes) -> bytes:
    """Replace the trailer `/ID` pair with a content-derived digest.

    A file with no `/ID` array is returned unchanged rather than raising:
    absence is valid PDF, not an error.
    """
    match = _ID_RE.search(raw)
    if match is None:
        return raw

    first, second = match.group(1), match.group(2)
    # Zero the identifiers before hashing so the digest depends on the
    # document's real content and never on the random value being replaced.
    neutral = (
        raw[: match.start(1)]
        + b"0" * len(first)
        + raw[match.end(1) : match.start(2)]
        + b"0" * len(second)
        + raw[match.end(2) :]
    )
    digest = hashlib.sha256(neutral).hexdigest().upper().encode("ascii")
    return (
        raw[: match.start(1)]
        + digest[: len(first)]
        + raw[match.end(1) : match.start(2)]
        + digest[: len(second)]
        + raw[match.end(2) :]
    )
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/domain/test_pdf_id.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/domain/pdf_id.py tests/unit/domain/test_pdf_id.py
rtk git commit -m "feat(translate): deterministic PDF trailer /ID normalization"
```

---

## Task 2: Group text objects into layout blocks

Per-object translation produces fragments. The block is the translation unit
and the layout contract. See ADR-2.

**Files:**
- Create: `src/docs/domain/block_grouping.py`
- Test: `tests/unit/domain/test_block_grouping.py`

**Interfaces:**
- Produces: `TextRun`, `TextBlock`, and
  `group_runs_into_blocks(runs, line_tolerance=2.0, gap_ratio=1.6) -> list[TextBlock]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_block_grouping.py
from docs.domain.block_grouping import TextRun, group_runs_into_blocks


def _run(text, x, y, w=50.0, h=10.0, page=0, size=12.0):
    return TextRun(text=text, x=x, y=y, width=w, height=h, page=page, font_size=size)


def test_runs_on_the_same_baseline_join_left_to_right():
    blocks = group_runs_into_blocks([_run("world", 60.0, 700.0), _run("Hello", 10.0, 700.0)])
    assert len(blocks) == 1
    assert blocks[0].text == "Hello world"


def test_adjacent_lines_join_into_one_block():
    blocks = group_runs_into_blocks([_run("First line", 10.0, 700.0), _run("second line", 10.0, 686.0)])
    assert len(blocks) == 1
    assert blocks[0].text == "First line second line"


def test_a_wide_vertical_gap_starts_a_new_block():
    blocks = group_runs_into_blocks([_run("Heading", 10.0, 700.0), _run("Body far below", 10.0, 400.0)])
    assert [b.text for b in blocks] == ["Heading", "Body far below"]


def test_blocks_never_span_pages():
    runs = [_run("Page one", 10.0, 700.0, page=0), _run("Page two", 10.0, 700.0, page=1)]
    blocks = group_runs_into_blocks(runs)
    assert len(blocks) == 2
    assert {b.page for b in blocks} == {0, 1}


def test_block_bbox_encloses_every_run_it_contains():
    runs = [_run("a", 10.0, 700.0, w=20.0, h=10.0), _run("b", 100.0, 686.0, w=30.0, h=10.0)]
    block = group_runs_into_blocks(runs)[0]
    assert (block.x, block.right, block.bottom, block.top) == (10.0, 130.0, 686.0, 710.0)


def test_no_runs_yields_no_blocks():
    assert group_runs_into_blocks([]) == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/domain/test_block_grouping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docs.domain.block_grouping'`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/block_grouping.py
"""Geometric grouping of PDF text runs into translation blocks.

A PDF stores text as positioned runs with no notion of a sentence. Translating
one run at a time asks the model to translate "Hello" and "world" separately,
which reads exactly as badly as it sounds. Runs are therefore grouped into
BLOCKS -- a block is both the unit of translation and the bounding box the
translated text must fit back into (design.md ADR-2).

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextRun:
    """One positioned text object as read from the PDF.

    `x`/`y` are the lower-left corner in PDF user space, where y grows UPWARD.
    """

    text: str
    x: float
    y: float
    width: float
    height: float
    page: int
    font_size: float
    # Serif vs sans is one of the most VISIBLE differences on a page, so the
    # family travels with the run: the writer maps it onto a standard font and
    # the visual-similarity gate would otherwise fail on a whole document that
    # silently turned from Times into Helvetica. Defaulted so pure-geometry
    # tests need not supply it.
    font_family: str = ""

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height


@dataclass
class TextBlock:
    """Runs that read as one unit and share one bounding box."""

    runs: list[TextRun] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.runs[0].page

    @property
    def text(self) -> str:
        return " ".join(run.text for run in self.runs).strip()

    @property
    def font_size(self) -> float:
        # The largest run wins: shrinking a heading to body size is a visible
        # regression; the fitter can still shrink from here if it must.
        return max(run.font_size for run in self.runs)

    @property
    def x(self) -> float:
        return min(run.x for run in self.runs)

    @property
    def right(self) -> float:
        return max(run.right for run in self.runs)

    @property
    def bottom(self) -> float:
        return min(run.y for run in self.runs)

    @property
    def top(self) -> float:
        return max(run.top for run in self.runs)

    @property
    def width(self) -> float:
        return self.right - self.x

    @property
    def height(self) -> float:
        return self.top - self.bottom


def _lines(runs: list[TextRun], tolerance: float) -> list[list[TextRun]]:
    """Cluster runs sharing a baseline, each line ordered left to right."""
    grouped: list[list[TextRun]] = []
    for run in sorted(runs, key=lambda r: (-r.y, r.x)):
        for line in grouped:
            if abs(line[0].y - run.y) <= tolerance:
                line.append(run)
                break
        else:
            grouped.append([run])
    for line in grouped:
        line.sort(key=lambda r: r.x)
    return grouped


def group_runs_into_blocks(
    runs: list[TextRun],
    line_tolerance: float = 2.0,
    gap_ratio: float = 1.6,
) -> list[TextBlock]:
    """Group `runs` into reading blocks, page by page, top to bottom.

    Two consecutive lines belong to the same block when the vertical gap
    between them is no more than `gap_ratio` times the taller line's height.
    A wider gap starts a new block.

    # ponytail: single-column assumption. Two columns side by side share
    # baselines and would be joined into one wrong block. `pdf-inspector`
    # reports `pages_with_columns`, and TranslateService refuses to trust this
    # grouping on those pages rather than producing silent nonsense
    # (design.md ADR-6). Phase 2 replaces this with pdf-inspector reading
    # order; do not add column detection here.
    """
    blocks: list[TextBlock] = []
    for page in sorted({run.page for run in runs}):
        current: TextBlock | None = None
        previous: list[TextRun] | None = None
        for line in _lines([r for r in runs if r.page == page], line_tolerance):
            if current is not None and previous is not None:
                tallest = max(max(r.height for r in previous), max(r.height for r in line))
                gap = min(r.y for r in previous) - max(r.top for r in line)
                if gap > tallest * gap_ratio:
                    blocks.append(current)
                    current = None
            if current is None:
                current = TextBlock()
            current.runs.extend(line)
            previous = line
        if current is not None:
            blocks.append(current)
    return blocks
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/domain/test_block_grouping.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/domain/block_grouping.py tests/unit/domain/test_block_grouping.py
rtk git commit -m "feat(translate): group PDF text runs into layout blocks"
```

---

## Task 3: Fit translated text back into its block

Translation expands. This decides how it fits, and — critically — reports when
it could not. See the "honest ceiling" section of `proposal.md`.

**Files:**
- Create: `src/docs/domain/text_fitting.py`
- Test: `tests/unit/domain/test_text_fitting.py`

**Interfaces:**
- Consumes: `TextBlock` from Task 2
- Produces: `FittedText(lines: list[str], font_size: float, overflowed: bool)` and
  `fit_text_to_block(text: str, block: TextBlock, min_scale: float = 0.6) -> FittedText`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_text_fitting.py
from docs.domain.block_grouping import TextBlock, TextRun
from docs.domain.text_fitting import fit_text_to_block


def _block(width, height, size=12.0):
    return TextBlock(runs=[TextRun("x", 0.0, 0.0, width, height, 0, size)])


def test_text_that_already_fits_keeps_its_font_size():
    fitted = fit_text_to_block("Hola", _block(200.0, 20.0))
    assert fitted.font_size == 12.0
    assert fitted.lines == ["Hola"]
    assert fitted.overflowed is False


def test_longer_text_wraps_onto_extra_lines_when_there_is_height():
    fitted = fit_text_to_block("Hola mundo entero y completo", _block(60.0, 60.0))
    assert len(fitted.lines) > 1
    assert fitted.overflowed is False


def test_font_shrinks_when_there_is_no_room_to_wrap():
    fitted = fit_text_to_block("Hola mundo entero y completo", _block(60.0, 14.0))
    assert fitted.font_size < 12.0


def test_font_never_shrinks_below_min_scale_and_reports_overflow():
    fitted = fit_text_to_block("palabra " * 200, _block(40.0, 14.0), min_scale=0.6)
    assert fitted.font_size >= 12.0 * 0.6
    assert fitted.overflowed is True


def test_empty_text_is_not_an_overflow():
    fitted = fit_text_to_block("", _block(100.0, 20.0))
    assert fitted.lines == []
    assert fitted.overflowed is False


def test_a_single_unbreakable_word_wider_than_the_block_overflows():
    fitted = fit_text_to_block("Donaudampfschiffahrtsgesellschaft", _block(10.0, 14.0))
    assert fitted.overflowed is True
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/domain/test_text_fitting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docs.domain.text_fitting'`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/text_fitting.py
"""Fit translated text back into the bounding box it came from.

Translation changes length -- EN->ES runs about 20-25% longer -- so the
translated string does not fit the box the original occupied. The strategy is
wrap first, shrink second, and REPORT third: a block that cannot be fitted
even at `min_scale` is marked `overflowed` so the pipeline can count it. A
silently clipped block is the failure mode this flag exists to prevent.

Pure geometry. No I/O, no imports from other layers.
"""
from __future__ import annotations

from dataclasses import dataclass

from docs.domain.block_grouping import TextBlock

# Mean glyph advance as a fraction of font size, for Helvetica-like faces.
# ponytail: a constant, not real font metrics. PDFium exposes
# `FPDFFont_GetGlyphWidth` for exact advances; swap this for a width callback
# injected by the adapter when a measured document shows the estimate drifting
# enough to misjudge a fit. Until then this keeps the domain layer pure and
# free of any PDF dependency.
_MEAN_ADVANCE_RATIO = 0.5

_LINE_SPACING = 1.18


@dataclass(frozen=True)
class FittedText:
    """The laid-out result, and whether it had to give up."""

    lines: list[str]
    font_size: float
    overflowed: bool


def _estimated_width(text: str, font_size: float) -> float:
    return len(text) * font_size * _MEAN_ADVANCE_RATIO


def _wrap(text: str, width: float, font_size: float) -> tuple[list[str], bool]:
    """Greedy word wrap. Returns the lines and whether any word was too wide."""
    lines: list[str] = []
    current = ""
    too_wide = False
    for word in text.split():
        if _estimated_width(word, font_size) > width:
            too_wide = True
        candidate = f"{current} {word}".strip()
        if current and _estimated_width(candidate, font_size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines, too_wide


def fit_text_to_block(text: str, block: TextBlock, min_scale: float = 0.6) -> FittedText:
    """Lay `text` out inside `block`, shrinking only as far as `min_scale`.

    `min_scale` is a floor rather than a target: text shrunk past roughly 60%
    of its neighbours stops reading as the same document, so overflowing
    visibly and being counted beats becoming illegible quietly.
    """
    if not text.strip():
        return FittedText(lines=[], font_size=block.font_size, overflowed=False)

    base = block.font_size
    floor = base * min_scale
    size = base
    while True:
        lines, word_too_wide = _wrap(text, block.width, size)
        needed = len(lines) * size * _LINE_SPACING
        if not word_too_wide and needed <= block.height:
            return FittedText(lines=lines, font_size=size, overflowed=False)
        if size <= floor:
            return FittedText(lines=lines, font_size=floor, overflowed=True)
        size = max(floor, size - 0.5)
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/domain/test_text_fitting.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/domain/text_fitting.py tests/unit/domain/test_text_fitting.py
rtk git commit -m "feat(translate): shrink-then-wrap text fitting with overflow reporting"
```

---

## Task 4: `PdfTextEditPort` and its `pypdfium2` adapter

**The most dangerous task in this plan.** ADR-1 documents a PDFium behaviour
that silently destroys text objects. Read it before writing a line.

**Files:**
- Create: `src/docs/domain/ports/pdf_text_edit_port.py`
- Create: `src/docs/infrastructure/pdf/pypdfium2_text_edit_adapter.py`
- Test: `tests/integration/infrastructure/test_pypdfium2_text_edit_adapter.py`

**Interfaces:**
- Consumes: `TextRun` (Task 2), `FittedText` (Task 3), `normalize_pdf_id` (Task 1)
- Produces:
  - `read_runs(pdf_path: Path) -> list[TextRun]`
  - `write_blocks(pdf_path: Path, out_path: Path, replacements: list[BlockReplacement]) -> WriteReport`
  - `BlockReplacement(page: int, remove: list[TextRun], fitted: FittedText, x: float, top: float)`
  - `WriteReport(fonts_substituted: int, blocks_written: int)`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/infrastructure/test_pypdfium2_text_edit_adapter.py
import hashlib

import pytest

from docs.domain.block_grouping import group_runs_into_blocks
from docs.domain.text_fitting import fit_text_to_block
from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import (
    BlockReplacement,
    Pypdfium2TextEditAdapter,
)


@pytest.fixture
def sample_pdf(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 4))
    fig.text(0.1, 0.8, "Hello world", fontsize=18)
    fig.text(0.1, 0.6, "Second line of text", fontsize=12)
    path = tmp_path / "original.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path


def _translate_all(adapter, src, dst, mapping):
    runs = adapter.read_runs(src)
    replacements = []
    for block in group_runs_into_blocks(runs):
        translated = mapping.get(block.text, block.text)
        replacements.append(
            BlockReplacement(
                page=block.page,
                remove=block.runs,
                fitted=fit_text_to_block(translated, block),
                x=block.x,
                top=block.top,
            )
        )
    return adapter.write_blocks(src, dst, replacements)


def test_read_runs_returns_text_with_geometry(sample_pdf):
    runs = Pypdfium2TextEditAdapter().read_runs(sample_pdf)
    assert {r.text for r in runs} == {"Hello world", "Second line of text"}
    assert all(r.width > 0 and r.height > 0 and r.font_size > 0 for r in runs)


def test_read_runs_reports_a_font_family_with_the_subset_tag_stripped(sample_pdf):
    """Serif vs sans is visible enough to fail the similarity gate on its own,
    so the family must survive the read rather than defaulting silently.

    The matplotlib fixture embeds `GGKEDP+DejaVuSans`; the six-letter subset
    tag must be gone and the family must remain.
    """
    runs = Pypdfium2TextEditAdapter().read_runs(sample_pdf)
    assert all(r.font_family for r in runs)
    assert all("+" not in r.font_family for r in runs)
    assert any("DejaVu" in r.font_family for r in runs)


def test_untouched_text_objects_survive_the_edit(sample_pdf, tmp_path):
    """ADR-1 regression: an open textpage during mutation silently destroys
    other text objects. This test is the reason that bug cannot come back."""
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo entero"})
    texts = {r.text for r in adapter.read_runs(out)}
    assert "Hola mundo entero" in texts
    assert "Second line of text" in texts, "an unrelated text object was destroyed"


def test_longer_translation_round_trips(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo entero y completo"})
    assert any("Hola mundo entero" in r.text for r in adapter.read_runs(out))


def test_two_identical_runs_produce_byte_identical_files(sample_pdf, tmp_path):
    adapter = Pypdfium2TextEditAdapter()
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    mapping = {"Hello world": "Hola mundo entero"}
    _translate_all(adapter, sample_pdf, a, mapping)
    _translate_all(adapter, sample_pdf, b, mapping)
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_page_count_is_preserved(sample_pdf, tmp_path):
    import pypdfium2 as pdfium

    adapter = Pypdfium2TextEditAdapter()
    out = tmp_path / "out.pdf"
    _translate_all(adapter, sample_pdf, out, {"Hello world": "Hola mundo"})
    before = pdfium.PdfDocument(str(sample_pdf))
    after = pdfium.PdfDocument(str(out))
    assert len(before) == len(after)
    before.close()
    after.close()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/integration/infrastructure/test_pypdfium2_text_edit_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError` on the adapter module

- [ ] **Step 3: Write the port**

```python
# src/docs/domain/ports/pdf_text_edit_port.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docs.domain.block_grouping import TextRun
from docs.domain.text_fitting import FittedText


@dataclass(frozen=True)
class BlockReplacement:
    """Remove `remove`, draw `fitted` starting at (`x`, `top`) on `page`."""

    page: int
    remove: list[TextRun]
    fitted: FittedText
    x: float
    top: float


@dataclass(frozen=True)
class WriteReport:
    """What the write had to compromise on, so the caller can report it."""

    blocks_written: int
    fonts_substituted: int


class PdfTextEditPort(Protocol):
    def read_runs(self, pdf_path: Path) -> list[TextRun]:
        """Every text object in the document, with page-space geometry."""
        ...

    def write_blocks(
        self, pdf_path: Path, out_path: Path, replacements: list[BlockReplacement]
    ) -> WriteReport:
        """Apply `replacements` to `pdf_path` and write `out_path`.

        The written bytes MUST be deterministic: the implementation is
        required to end in `domain.pdf_id.normalize_pdf_id`, because PDFium
        stamps a random trailer `/ID` on every save (design.md ADR-3).
        """
        ...
```

- [ ] **Step 4: Write the adapter**

```python
# src/docs/infrastructure/pdf/pypdfium2_text_edit_adapter.py
"""In-place PDF text editing via the raw PDFium API.

Two PDFium behaviours make this file more delicate than it looks, both
measured rather than inferred (design.md ADR-1 and ADR-3):

1. Mutating page objects while a textpage is open SILENTLY DESTROYS unrelated
   text objects -- a 3-object page came back as 2 with nothing raised. The
   read phase and the write phase are therefore strictly separated by
   `FPDFText_ClosePage`, and that ordering is not an optimisation to tidy up.
2. Every save stamps a random trailer `/ID`, so identical input yields
   different bytes. The save therefore ends in `normalize_pdf_id`.

`FPDFPage_RemoveObject` transfers ownership to the caller, so every removal is
paired with `FPDFPageObj_Destroy`.
"""
from __future__ import annotations

import ctypes
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from docs.domain.block_grouping import TextRun
from docs.domain.pdf_id import normalize_pdf_id
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, WriteReport

_LINE_SPACING = 1.18

# Original fonts are embedded as SUBSETS holding only the glyphs the document
# already used, so a target-language glyph that never appeared is simply not
# there -- "present" is not "usable". Map the family onto a base-14 standard
# font, which always has full Latin coverage, and count the substitution.
# ponytail: base-14 only, so non-Latin targets (Cyrillic, CJK, Arabic) are out
# of reach. Upgrade path is `FPDFText_LoadFont` with a bundled Noto face,
# which is a licensing and file-size decision, not a code one.
_STANDARD_FONTS = {
    "times": b"Times-Roman",
    "serif": b"Times-Roman",
    "courier": b"Courier",
    "mono": b"Courier",
}
_DEFAULT_FONT = b"Helvetica"


def _widestring(text: str):
    buffer = ctypes.create_string_buffer(text.encode("utf-16-le") + b"\x00\x00")
    return ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort))


def _standard_font_for(family: str) -> bytes:
    """Map an embedded family onto a base-14 font.

    Phase 1 ALWAYS substitutes -- there is no path here that reuses the
    original embedded font -- so the caller counts every block as a
    substitution. That number is meant to look large; it is the honest size of
    the compromise, not a bug to tune away.
    """
    lowered = family.lower()
    for needle, font in _STANDARD_FONTS.items():
        if needle in lowered:
            return font
    return _DEFAULT_FONT


class Pypdfium2TextEditAdapter:
    """`PdfTextEditPort` implementation over the raw PDFium C API."""

    def read_runs(self, pdf_path: Path) -> list[TextRun]:
        runs: list[TextRun] = []
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            for page_index in range(len(document)):
                page = document[page_index]
                textpage = pdfium_c.FPDFText_LoadPage(page.raw)
                try:
                    runs.extend(self._runs_on_page(page, textpage, page_index))
                finally:
                    # Not a tidy-up: leaving this open across a later mutation
                    # is what destroys objects (ADR-1).
                    pdfium_c.FPDFText_ClosePage(textpage)
        finally:
            document.close()
        return runs

    def _runs_on_page(self, page, textpage, page_index: int) -> list[TextRun]:
        found: list[TextRun] = []
        for i in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
            obj = pdfium_c.FPDFPage_GetObject(page.raw, i)
            if pdfium_c.FPDFPageObj_GetType(obj) != pdfium_c.FPDF_PAGEOBJ_TEXT:
                continue
            length = pdfium_c.FPDFTextObj_GetText(obj, textpage, None, 0)
            buffer = ctypes.create_string_buffer(length * 2)
            pdfium_c.FPDFTextObj_GetText(
                obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
            )
            text = buffer.raw[: length * 2].decode("utf-16-le").rstrip("\x00")
            if not text.strip():
                continue
            left, bottom, right, top = (ctypes.c_float() for _ in range(4))
            pdfium_c.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
            size = ctypes.c_float()
            pdfium_c.FPDFTextObj_GetFontSize(obj, size)
            found.append(
                TextRun(
                    text=text,
                    x=left.value,
                    y=bottom.value,
                    width=right.value - left.value,
                    height=top.value - bottom.value,
                    page=page_index,
                    font_size=size.value,
                    font_family=self._family_of(obj),
                )
            )
        return found

    def _family_of(self, obj) -> str:
        """The run's font family, or "" when PDFium cannot report one.

        Use `FPDFFont_GetBaseFontName`, NOT `FPDFFont_GetFamilyName`: the
        latter is present, returns success, and yields an empty string for
        embedded subset fonts (measured on a matplotlib PDF -- length 1, just
        the terminator). "Present" is not "usable", and a silently empty
        family would send every serif document back as sans.

        The returned name carries a subset tag -- `GGKEDP+DejaVuSans` -- which
        is itself the evidence that the embedded font holds only the glyphs
        the document already used. Strip the tag; keep the family.
        """
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        if not font:
            return ""
        length = pdfium_c.FPDFFont_GetBaseFontName(font, None, 0)
        if length <= 0:
            return ""
        buffer = ctypes.create_string_buffer(length)
        pdfium_c.FPDFFont_GetBaseFontName(font, buffer, length)
        name = buffer.value.decode("utf-8", errors="replace")
        # Subset tags are exactly six uppercase letters and a "+".
        prefix, plus, rest = name.partition("+")
        if plus and len(prefix) == 6 and prefix.isupper() and prefix.isalpha():
            return rest
        return name

    def write_blocks(
        self, pdf_path: Path, out_path: Path, replacements: list[BlockReplacement]
    ) -> WriteReport:
        document = pdfium.PdfDocument(str(pdf_path))
        substituted = 0
        try:
            by_page: dict[int, list[BlockReplacement]] = {}
            for replacement in replacements:
                by_page.setdefault(replacement.page, []).append(replacement)

            for page_index, page_replacements in by_page.items():
                page = document[page_index]
                # READ phase: locate the objects to remove, textpage open.
                targets = self._targets_for(page, page_replacements)
                # WRITE phase: textpage is closed inside _targets_for before
                # any mutation happens (ADR-1).
                for replacement, objects in targets:
                    for obj in objects:
                        pdfium_c.FPDFPage_RemoveObject(page.raw, obj)
                        pdfium_c.FPDFPageObj_Destroy(obj)
                    substituted += self._draw(document, page, replacement)
                pdfium_c.FPDFPage_GenerateContent(page.raw)

            document.save(str(out_path))
        finally:
            document.close()

        # PDFium stamps a random /ID on save; without this every byte-identity
        # test in this capability is flaky for a reason that is a real bug.
        out_path.write_bytes(normalize_pdf_id(out_path.read_bytes()))
        return WriteReport(blocks_written=len(replacements), fonts_substituted=substituted)

    def _targets_for(self, page, replacements: list[BlockReplacement]):
        """Match each replacement to its page objects, then CLOSE the textpage."""
        wanted = {
            (replacement_index, run.text, round(run.x, 1), round(run.y, 1))
            for replacement_index, replacement in enumerate(replacements)
            for run in replacement.remove
        }
        lookup: dict[tuple[str, float, float], int] = {
            (text, x, y): index for index, text, x, y in wanted
        }
        textpage = pdfium_c.FPDFText_LoadPage(page.raw)
        try:
            matched: dict[int, list] = {i: [] for i in range(len(replacements))}
            for i in range(pdfium_c.FPDFPage_CountObjects(page.raw)):
                obj = pdfium_c.FPDFPage_GetObject(page.raw, i)
                if pdfium_c.FPDFPageObj_GetType(obj) != pdfium_c.FPDF_PAGEOBJ_TEXT:
                    continue
                length = pdfium_c.FPDFTextObj_GetText(obj, textpage, None, 0)
                buffer = ctypes.create_string_buffer(length * 2)
                pdfium_c.FPDFTextObj_GetText(
                    obj, textpage, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)), length
                )
                text = buffer.raw[: length * 2].decode("utf-16-le").rstrip("\x00")
                left, bottom, right, top = (ctypes.c_float() for _ in range(4))
                pdfium_c.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
                key = (text, round(left.value, 1), round(bottom.value, 1))
                if key in lookup:
                    matched[lookup[key]].append(obj)
        finally:
            pdfium_c.FPDFText_ClosePage(textpage)
        return [(replacements[i], matched[i]) for i in sorted(matched)]

    def _draw(self, document, page, replacement: BlockReplacement) -> int:
        family = replacement.remove[0].font_family if replacement.remove else ""
        font = pdfium_c.FPDFText_LoadStandardFont(document.raw, _standard_font_for(family))
        size = replacement.fitted.font_size
        for line_number, line in enumerate(replacement.fitted.lines):
            obj = pdfium_c.FPDFPageObj_CreateTextObj(document.raw, font, size)
            pdfium_c.FPDFText_SetText(obj, _widestring(line))
            pdfium_c.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
            baseline = replacement.top - size - (line_number * size * _LINE_SPACING)
            pdfium_c.FPDFPageObj_Transform(obj, 1, 0, 0, 1, replacement.x, baseline)
            pdfium_c.FPDFPage_InsertObject(page.raw, obj)
        return 1
```

- [ ] **Step 5: Run tests and confirm they pass**

Run: `uv run pytest tests/integration/infrastructure/test_pypdfium2_text_edit_adapter.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
rtk git add src/docs/domain/ports/pdf_text_edit_port.py src/docs/infrastructure/pdf/pypdfium2_text_edit_adapter.py tests/integration/infrastructure/test_pypdfium2_text_edit_adapter.py
rtk git commit -m "feat(translate): in-place PDF text editing via raw PDFium"
```

---

## Task 5: Translation memory — the source of determinism

The LLM is not deterministic. The cache is. See ADR-4.

**Files:**
- Create: `src/docs/domain/translation_memory_key.py`
- Create: `src/docs/domain/ports/translation_memory_port.py`
- Create: `src/docs/infrastructure/translate/filesystem_translation_memory.py`
- Test: `tests/unit/infrastructure/test_filesystem_translation_memory.py`

**Interfaces:**
- Produces: `memory_key(text, source_lang, target_lang, engine_id, glossary_version) -> str`
  in **domain** (`TranslateService` needs it, and application must never import
  infrastructure), plus `get(key) -> str | None` and
  `put(key, source_text, translation) -> None` on the adapter.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_filesystem_translation_memory.py
from docs.domain.translation_memory_key import memory_key
from docs.infrastructure.translate.filesystem_translation_memory import (
    FilesystemTranslationMemory,
)


def test_the_same_inputs_produce_the_same_key():
    a = memory_key("Hello", "en", "es", "llm-v1", "g1")
    b = memory_key("Hello", "en", "es", "llm-v1", "g1")
    assert a == b


def test_every_component_changes_the_key():
    base = memory_key("Hello", "en", "es", "llm-v1", "g1")
    assert memory_key("Hello!", "en", "es", "llm-v1", "g1") != base
    assert memory_key("Hello", "en", "fr", "llm-v1", "g1") != base
    assert memory_key("Hello", "de", "es", "llm-v1", "g1") != base
    assert memory_key("Hello", "en", "es", "llm-v2", "g1") != base
    assert memory_key("Hello", "en", "es", "llm-v1", "g2") != base


def test_a_stored_translation_is_read_back(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Hello", "Hola")
    assert memory.get("k1") == "Hola"


def test_a_missing_key_returns_none(tmp_path):
    assert FilesystemTranslationMemory(tmp_path).get("absent") is None


def test_the_cache_survives_a_new_instance(tmp_path):
    FilesystemTranslationMemory(tmp_path).put("k1", "Hello", "Hola")
    assert FilesystemTranslationMemory(tmp_path).get("k1") == "Hola"


def test_writes_are_atomic_leaving_no_partial_files(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Hello", "Hola")
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/infrastructure/test_filesystem_translation_memory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/translation_memory_key.py
"""The cache key that makes a non-deterministic engine reproducible.

This lives in the DOMAIN, not beside the filesystem adapter, because
`TranslateService` computes the key and application code must never import
infrastructure. The key is pure hashing and has no business knowing where the
entry is stored.

The engine id and glossary version are part of the key on purpose: changing
either SHOULD produce a new translation rather than silently reusing one made
under different rules.
"""
from __future__ import annotations

import hashlib

# NUL joins the components so no combination of them can collide by
# concatenation -- ("ab", "c") and ("a", "bc") must not share a key.
_SEPARATOR = "\x00"


def memory_key(
    text: str, source_lang: str, target_lang: str, engine_id: str, glossary_version: str
) -> str:
    payload = _SEPARATOR.join([text, source_lang, target_lang, engine_id, glossary_version])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

```python
# src/docs/infrastructure/translate/filesystem_translation_memory.py
"""Content-addressed translation memory on disk.

An LLM is not deterministic -- batching, model versions and tie-breaks all
move the output -- but this harness requires byte-identical reruns. The cache
is what supplies that: the first run translates and stores, every later run is
a hit and reproduces the same bytes for free (design.md ADR-4).

Writes are temp-then-rename, matching `infrastructure/ingest/atomic_ingest_write.py`,
so an interrupted run never leaves a partial entry a later run would trust.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class FilesystemTranslationMemory:
    """`TranslationMemoryPort` over one directory of JSON entries."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def get(self, key: str) -> str | None:
        path = self._root / f"{key}.json"
        if not path.is_file():
            return None
        try:
            return str(json.loads(path.read_text(encoding="utf-8"))["translation"])
        except (json.JSONDecodeError, KeyError, OSError):
            # A corrupt entry is a cache miss, never a crash: the run
            # retranslates and overwrites it.
            return None

    def put(self, key: str, source_text: str, translation: str) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{key}.json"
        temp = path.with_suffix(".json.tmp")
        # `source` is stored for auditability only -- nothing reads it back.
        payload = {"source": source_text, "translation": translation}
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
```

Also create `src/docs/domain/ports/translation_memory_port.py` with a
`TranslationMemoryPort` Protocol declaring `get(key: str) -> str | None` and
`put(key: str, source_text: str, translation: str) -> None`.

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/infrastructure/test_filesystem_translation_memory.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/domain/translation_memory_key.py src/docs/domain/ports/translation_memory_port.py src/docs/infrastructure/translate/ tests/unit/infrastructure/test_filesystem_translation_memory.py
rtk git commit -m "feat(translate): content-addressed translation memory"
```

---

## Task 6: `TranslationPort` and the never-refuse guard

**This is the task that delivers the product promise.** A model's refusal must
degrade one block, never the document. See ADR-5.

**Files:**
- Create: `src/docs/domain/ports/translation_port.py`
- Create: `src/docs/domain/translation_guard.py`
- Test: `tests/unit/domain/test_translation_guard.py`

**Interfaces:**
- Produces: `TranslationOutcome(text: str, translated: bool)` and
  `guarded_translate(block_text, source_lang, target_lang, call) -> TranslationOutcome`
  where `call` is `Callable[[str], str]` and may raise.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_translation_guard.py
from docs.domain.translation_guard import guarded_translate


def test_a_normal_translation_is_returned_and_marked_translated():
    outcome = guarded_translate("Hello", "en", "es", lambda _: "Hola")
    assert outcome == ("Hola", True)


def test_an_empty_response_is_retried_once_then_passes_through():
    calls = []

    def call(text):
        calls.append(text)
        return ""

    outcome = guarded_translate("Hello", "en", "es", call)
    assert len(calls) == 2, "must retry exactly once"
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_a_retry_that_succeeds_is_used():
    responses = iter(["", "Hola"])

    outcome = guarded_translate("Hello", "en", "es", lambda _: next(responses))
    assert outcome == ("Hola", True)


def test_a_refusal_passes_the_original_through_and_never_raises():
    def refuse(_):
        return "I cannot help with translating this content."

    outcome = guarded_translate("Hello", "en", "es", refuse)
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_an_exception_from_the_engine_never_escapes():
    def explode(_):
        raise RuntimeError("provider is down")

    outcome = guarded_translate("Hello", "en", "es", explode)
    assert outcome.text == "Hello"
    assert outcome.translated is False


def test_an_unchanged_response_counts_as_not_translated():
    outcome = guarded_translate("Hello", "en", "es", lambda text: text)
    assert outcome.translated is False


def test_whitespace_only_input_is_passed_through_without_calling_the_engine():
    called = False

    def call(_):
        nonlocal called
        called = True
        return "x"

    outcome = guarded_translate("   ", "en", "es", call)
    assert called is False
    assert outcome.text == "   "
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/domain/test_translation_guard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/translation_guard.py
"""The rule that a model never gets a vote on whether to translate.

A translator that declines is a broken tool. This module is the harness-side
half of that promise (design.md ADR-5): the model sees one block and a target
language, and whatever comes back, the RUN CONTINUES. A refusal, an empty
answer, an exception or an unchanged string all degrade exactly one block --
the original text passes through and the block is counted -- and the caller
reports the count in its own pipeline line.

Nothing here instructs the model. These are harness mechanics, which is the
point: an instruction can be ignored, a code path cannot.

Pure logic. No I/O, no imports from other layers.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

# Matched case-insensitively against the WHOLE response. Deliberately narrow:
# a false positive here throws away a real translation, and the fallbacks
# below (empty, unchanged, raised) already catch most failures on their own.
_REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "i won't",
    "i am unable",
    "i'm unable",
    "as an ai",
    "no puedo",
    "lo siento, no",
)


class TranslationOutcome(NamedTuple):
    text: str
    translated: bool


def _is_refusal(response: str) -> bool:
    lowered = response.strip().lower()
    return any(lowered.startswith(marker) for marker in _REFUSAL_MARKERS)


def _usable(response: str, original: str) -> bool:
    stripped = response.strip()
    if not stripped:
        return False
    if stripped == original.strip():
        return False
    return not _is_refusal(stripped)


def guarded_translate(
    block_text: str,
    source_lang: str,
    target_lang: str,
    call: Callable[[str], str],
) -> TranslationOutcome:
    """Translate `block_text`, or pass it through. Never raises.

    Exactly one retry: a transient hiccup deserves a second chance, a
    systematic refusal does not deserve a third.
    """
    if not block_text.strip():
        return TranslationOutcome(block_text, False)

    for _ in range(2):
        try:
            response = call(block_text)
        except Exception:
            # The engine being down degrades a block, not the document.
            continue
        if _usable(response, block_text):
            return TranslationOutcome(response.strip(), True)

    return TranslationOutcome(block_text, False)
```

Also create `src/docs/domain/ports/translation_port.py` with a
`TranslationPort` Protocol declaring
`translate(text: str, source_lang: str, target_lang: str) -> str` and an
`engine_id: str` attribute used by `memory_key`.

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/domain/test_translation_guard.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/domain/translation_guard.py src/docs/domain/ports/translation_port.py tests/unit/domain/test_translation_guard.py
rtk git commit -m "feat(translate): never-refuse translation guard with single retry"
```

---

## Task 7: PDF classification gate

`pdf-inspector` tells us whether this document can be translated at all, and
where our own block grouping is not to be trusted. See ADR-6.

**Files:**
- Modify: `pyproject.toml` — add `"pdf-inspector>=0.1"` to `dependencies`
- Create: `src/docs/domain/ports/pdf_classify_port.py`
- Create: `src/docs/infrastructure/pdf/pdf_inspector_classify_adapter.py`
- Test: `tests/integration/infrastructure/test_pdf_inspector_classify_adapter.py`

**Interfaces:**
- Produces: `PdfClassification(pdf_type: str, pages_needing_ocr: list[int],
  pages_with_columns: list[int], has_encoding_issues: bool, page_count: int)` and
  `classify(pdf_path: Path) -> PdfClassification`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/infrastructure/test_pdf_inspector_classify_adapter.py
import pytest

from docs.infrastructure.pdf.pdf_inspector_classify_adapter import PdfInspectorClassifyAdapter

pytest.importorskip("pdf_inspector")


@pytest.fixture
def text_pdf(tmp_path):
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(6, 4))
    fig.text(0.1, 0.8, "Hello world", fontsize=18)
    path = tmp_path / "text.pdf"
    fig.savefig(path)
    plt.close(fig)
    return path


def test_a_text_pdf_is_classified_text_based(text_pdf):
    result = PdfInspectorClassifyAdapter().classify(text_pdf)
    assert result.pdf_type == "text_based"
    assert result.page_count == 1


def test_a_text_pdf_needs_no_ocr(text_pdf):
    assert PdfInspectorClassifyAdapter().classify(text_pdf).pages_needing_ocr == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/integration/infrastructure/test_pdf_inspector_classify_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Add the dependency and implement**

```bash
uv add pdf-inspector
```

```python
# src/docs/infrastructure/pdf/pdf_inspector_classify_adapter.py
"""PDF classification via `pdf-inspector` (Rust, MIT, PDFium-backed).

`pdf-inspector` cannot write PDFs, so it is used only for what it is uniquely
good at: telling us what KIND of document this is before we try to translate
it (design.md ADR-6).

Two of its signals gate real behaviour rather than decorating a report:
`pdf_type` decides whether there is a text layer to translate at all, and
`pages_with_columns` marks the pages where our own single-column block
grouping is not to be trusted.
"""
from __future__ import annotations

from pathlib import Path

import pdf_inspector

from docs.domain.ports.pdf_classify_port import PdfClassification


class PdfInspectorClassifyAdapter:
    """`PdfClassifyPort` implementation."""

    def classify(self, pdf_path: Path) -> PdfClassification:
        result = pdf_inspector.process_pdf(str(pdf_path))
        return PdfClassification(
            pdf_type=result.pdf_type,
            page_count=result.page_count,
            pages_needing_ocr=list(result.pages_needing_ocr),
            pages_with_columns=list(result.pages_with_columns),
            has_encoding_issues=bool(result.has_encoding_issues),
        )
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/integration/infrastructure/test_pdf_inspector_classify_adapter.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
rtk git add pyproject.toml uv.lock src/docs/domain/ports/pdf_classify_port.py src/docs/infrastructure/pdf/pdf_inspector_classify_adapter.py tests/integration/infrastructure/test_pdf_inspector_classify_adapter.py
rtk git commit -m "feat(translate): PDF classification gate via pdf-inspector"
```

---

## Task 8: `TranslateService` orchestration

Where the pieces meet, and where degradation gets counted.

**Files:**
- Create: `src/docs/application/translate.py`
- Test: `tests/unit/application/test_translate_service.py`

**Interfaces:**
- Consumes: every port from Tasks 4-7
- Produces: `TranslateReport(blocks_total, blocks_translated, blocks_from_cache,
  blocks_overflowed, fonts_substituted, pages_untrusted, output_path)` and
  `TranslateService.translate_pdf(src, out, target_lang, source_lang="auto") -> TranslateReport`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/application/test_translate_service.py
import pytest

from docs.application.translate import TranslateService, UntranslatablePdfError
from docs.domain.block_grouping import TextRun
from docs.domain.ports.pdf_classify_port import PdfClassification
from docs.domain.ports.pdf_text_edit_port import WriteReport


class FakeClassifier:
    def __init__(self, pdf_type="text_based", columns=None):
        self._type, self._columns = pdf_type, columns or []

    def classify(self, path):
        return PdfClassification(self._type, 1, [], self._columns, False)


class FakeEditor:
    engine_id = "fake"

    def __init__(self):
        self.written = None

    def read_runs(self, path):
        return [TextRun("Hello world", 10.0, 700.0, 90.0, 14.0, 0, 12.0)]

    def write_blocks(self, src, out, replacements):
        self.written = replacements
        out.write_bytes(b"%PDF-1.4 fake\n")
        return WriteReport(blocks_written=len(replacements), fonts_substituted=1)


class FakeTranslator:
    engine_id = "fake-llm-v1"

    def __init__(self, responses=None):
        self.responses, self.calls = responses or {}, []

    def translate(self, text, source_lang, target_lang):
        self.calls.append(text)
        return self.responses.get(text, f"[es] {text}")


class MemoryDict:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, source_text, translation):
        self.data[key] = translation


def _service(classifier=None, translator=None, memory=None, editor=None):
    return TranslateService(
        classifier=classifier or FakeClassifier(),
        editor=editor or FakeEditor(),
        translator=translator or FakeTranslator(),
        memory=memory if memory is not None else MemoryDict(),
    )


def test_a_scanned_pdf_is_refused_with_a_clear_reason(tmp_path):
    service = _service(classifier=FakeClassifier(pdf_type="scanned"))
    with pytest.raises(UntranslatablePdfError, match="capa de texto"):
        service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")


def test_blocks_are_translated_and_counted(tmp_path):
    report = _service().translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    assert report.blocks_total == 1
    assert report.blocks_translated == 1


def test_the_second_run_hits_the_cache_and_calls_no_engine(tmp_path):
    memory, translator = MemoryDict(), FakeTranslator()
    service = _service(translator=translator, memory=memory)
    service.translate_pdf(tmp_path / "in.pdf", tmp_path / "a.pdf", "es")
    calls_after_first = len(translator.calls)
    report = service.translate_pdf(tmp_path / "in.pdf", tmp_path / "b.pdf", "es")
    assert len(translator.calls) == calls_after_first, "engine called on a cache hit"
    assert report.blocks_from_cache == 1


def test_a_refusing_engine_still_produces_a_document(tmp_path):
    translator = FakeTranslator(responses={"Hello world": "I cannot help with that."})
    report = _service(translator=translator).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert report.blocks_total == 1
    assert report.blocks_translated == 0
    assert report.output_path.exists(), "a refusal must not stop the document"


def test_a_column_page_is_reported_as_untrusted(tmp_path):
    service = _service(classifier=FakeClassifier(columns=[1]))
    report = service.translate_pdf(tmp_path / "in.pdf", tmp_path / "out.pdf", "es")
    assert report.pages_untrusted == [1]


def test_a_refused_block_is_not_written_to_the_cache(tmp_path):
    memory = MemoryDict()
    translator = FakeTranslator(responses={"Hello world": "I cannot help with that."})
    _service(translator=translator, memory=memory).translate_pdf(
        tmp_path / "in.pdf", tmp_path / "out.pdf", "es"
    )
    assert memory.data == {}, "a refusal must never be cached as a translation"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/application/test_translate_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docs.application.translate'`

- [ ] **Step 3: Implement**

```python
# src/docs/application/translate.py
"""Translate a PDF in place, preserving its layout.

The flow is: classify, read runs, group into blocks, translate each block
through the cache, fit the result back into the block's box, write, report.

Every compromise made along the way is COUNTED and returned, because a stage
that degrades where only a file can tell you reads as a clean success -- the
lesson `qa-docx` taught this repo after 24 silent runs. Font substitutions,
overflowed blocks, untranslated blocks and untrusted pages all surface in the
pipeline's own line.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docs.domain.block_grouping import group_runs_into_blocks
from docs.domain.ports.pdf_classify_port import PdfClassifyPort
from docs.domain.ports.pdf_text_edit_port import BlockReplacement, PdfTextEditPort
from docs.domain.ports.translation_memory_port import TranslationMemoryPort
from docs.domain.ports.translation_port import TranslationPort
from docs.domain.text_fitting import fit_text_to_block
from docs.domain.translation_guard import guarded_translate
from docs.domain.translation_memory_key import memory_key

_TRANSLATABLE = {"text_based", "mixed"}
_GLOSSARY_VERSION = "1"


class UntranslatablePdfError(RuntimeError):
    """Raised only when there is genuinely nothing to translate.

    This is NOT a refusal: it means the document has no text layer, so no
    engine could translate it either. The message names the remedy.
    """


@dataclass
class TranslateReport:
    output_path: Path
    blocks_total: int = 0
    blocks_translated: int = 0
    blocks_from_cache: int = 0
    blocks_overflowed: int = 0
    fonts_substituted: int = 0
    pages_untrusted: list[int] = field(default_factory=list)

    def to_line(self) -> str:
        """One Spanish line for the pipeline, naming every compromise."""
        parts = [f"traducido: {self.blocks_translated}/{self.blocks_total} bloques"]
        if self.blocks_from_cache:
            parts.append(f"{self.blocks_from_cache} desde memoria")
        untranslated = self.blocks_total - self.blocks_translated
        if untranslated:
            parts.append(f"{untranslated} sin traducir")
        if self.blocks_overflowed:
            parts.append(f"{self.blocks_overflowed} no entraron en su caja")
        if self.fonts_substituted:
            parts.append(f"{self.fonts_substituted} con fuente sustituida")
        if self.pages_untrusted:
            pages = ", ".join(str(p) for p in self.pages_untrusted)
            parts.append(f"paginas multicolumna sin verificar: {pages}")
        return "; ".join(parts)


class TranslateService:
    def __init__(
        self,
        classifier: PdfClassifyPort,
        editor: PdfTextEditPort,
        translator: TranslationPort,
        memory: TranslationMemoryPort,
    ) -> None:
        self._classifier = classifier
        self._editor = editor
        self._translator = translator
        self._memory = memory

    def translate_pdf(
        self, src: Path, out: Path, target_lang: str, source_lang: str = "auto"
    ) -> TranslateReport:
        classification = self._classifier.classify(src)
        if classification.pdf_type not in _TRANSLATABLE:
            raise UntranslatablePdfError(
                f"el PDF no tiene capa de texto (tipo: {classification.pdf_type}); "
                "se requiere OCR, que todavia no esta disponible"
            )

        report = TranslateReport(
            output_path=out, pages_untrusted=list(classification.pages_with_columns)
        )
        blocks = group_runs_into_blocks(self._editor.read_runs(src))
        report.blocks_total = len(blocks)

        replacements: list[BlockReplacement] = []
        for block in blocks:
            translated, from_cache, ok = self._translate_block(block.text, source_lang, target_lang)
            report.blocks_translated += int(ok)
            report.blocks_from_cache += int(from_cache)
            fitted = fit_text_to_block(translated, block)
            report.blocks_overflowed += int(fitted.overflowed)
            replacements.append(
                BlockReplacement(
                    page=block.page,
                    remove=block.runs,
                    fitted=fitted,
                    x=block.x,
                    top=block.top,
                )
            )

        write_report = self._editor.write_blocks(src, out, replacements)
        report.fonts_substituted = write_report.fonts_substituted
        return report

    def _translate_block(
        self, text: str, source_lang: str, target_lang: str
    ) -> tuple[str, bool, bool]:
        key = memory_key(
            text, source_lang, target_lang, self._translator.engine_id, _GLOSSARY_VERSION
        )
        cached = self._memory.get(key)
        if cached is not None:
            return cached, True, True

        outcome = guarded_translate(
            text,
            source_lang,
            target_lang,
            lambda t: self._translator.translate(t, source_lang, target_lang),
        )
        if outcome.translated:
            # Only a real translation is cached. Caching a pass-through would
            # make one bad run permanent for every future run.
            self._memory.put(key, text, outcome.text)
        return outcome.text, False, outcome.translated
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `uv run pytest tests/unit/application/test_translate_service.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
rtk git add src/docs/application/translate.py tests/unit/application/test_translate_service.py
rtk git commit -m "feat(translate): TranslateService orchestration with degradation reporting"
```

---

## Task 9: CLI command and composition root wiring

**Files:**
- Create: `src/docs/cli/commands/translate.py`
- Modify: `src/docs/cli/main.py` — `app.add_typer(translate_app)`
- Modify: `src/docs/cli/_shared.py` — build and expose the four adapters
- Modify: `src/docs/domain/config_vocabulary.py` — add the `translate` block
- Test: `tests/unit/cli/test_translate_command.py`

**Interfaces:**
- Consumes: `TranslateService` (Task 8)
- Produces: `docs translate <input.pdf> --to <lang> [--from auto] [--out <path>]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_translate_command.py
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()


def test_the_command_is_registered_with_help_text():
    result = runner.invoke(app, ["translate", "--help"])
    assert result.exit_code == 0
    assert "--to" in result.stdout


def test_a_missing_input_file_fails_with_a_spanish_message(tmp_path):
    result = runner.invoke(app, ["translate", str(tmp_path / "nope.pdf"), "--to", "es"])
    assert result.exit_code != 0
    assert "no existe" in result.stdout.lower()


def test_the_target_language_is_required(tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    assert runner.invoke(app, ["translate", str(src)]).exit_code != 0
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/cli/test_translate_command.py -v`
Expected: FAIL — no `translate` command registered

- [ ] **Step 3: Implement the command**

```python
# src/docs/cli/commands/translate.py
"""`docs translate` -- translate a document, unconditionally.

There is no content gate here and there must never be one. If a user asks for
a translation, it translates; a refusal is reported per block by
`TranslateService` and never stops the run (design.md ADR-5).
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.application.translate import UntranslatablePdfError
from docs.cli._shared import build_deps

translate_app = typer.Typer()


@translate_app.command("translate")
def translate(
    source: Path = typer.Argument(..., help="Archivo PDF a traducir."),
    to: str = typer.Option(..., "--to", help="Idioma destino (por ejemplo: es, en, pt)."),
    source_lang: str = typer.Option("auto", "--from", help="Idioma origen; 'auto' lo detecta."),
    out: Path | None = typer.Option(None, "--out", help="Ruta de salida del PDF traducido."),
) -> None:
    """Traduce un PDF conservando su maquetacion."""
    if not source.is_file():
        typer.echo(f"El archivo no existe: {source}")
        raise typer.Exit(code=1)

    destination = out or source.with_name(f"{source.stem}.{to}{source.suffix}")
    service = build_deps().translate_service
    try:
        report = service.translate_pdf(source, destination, to, source_lang)
    except UntranslatablePdfError as error:
        typer.echo(f"No se puede traducir: {error}")
        raise typer.Exit(code=1) from error

    typer.echo(report.to_line())
    typer.echo(f"Escrito: {destination}")
```

- [ ] **Step 4: Wire the composition root**

In `src/docs/cli/_shared.py`, inside `Deps`, add a `translate_service` built from
`PdfInspectorClassifyAdapter()`, `Pypdfium2TextEditAdapter()`, the configured
`TranslationPort` adapter, and `FilesystemTranslationMemory(Path(config["paths"]["translations_dir"]))`.

In `src/docs/cli/main.py`, add `app.add_typer(translate_app)` alongside the
existing routers.

In `src/docs/domain/config_vocabulary.py`, add to `SCANNED_CONFIG_KEYS`:

```python
    "translate": {
        "default_target_lang": {},
        "min_font_scale": {},
        "visual_similarity_threshold": {},
    },
```

and add `"translations_dir"` under the existing `"paths"` block.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green, including `tests/architecture/test_config_vocabulary.py` and
`tests/unit/cli/test_command_help_coverage.py`

- [ ] **Step 6: Commit**

```bash
rtk git add src/docs/cli/ src/docs/domain/config_vocabulary.py tests/unit/cli/test_translate_command.py
rtk git commit -m "feat(translate): docs translate CLI command and wiring"
```

---

## Task 10: The visual similarity gate

**The task that turns "se ve igual" from a claim into a number.** See ADR-8.

**Files:**
- Create: `src/docs/domain/visual_similarity.py`
- Test: `tests/integration/test_translate_visual_similarity.py`

**Interfaces:**
- Consumes: the existing `PdfRenderPort` (`render_pages`)
- Produces: `page_similarity(before_png: Path, after_png: Path) -> float` in `[0.0, 1.0]`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_translate_visual_similarity.py
import pytest
from PIL import Image

from docs.domain.visual_similarity import page_similarity


def _png(tmp_path, name, color, box=None):
    image = Image.new("RGB", (200, 200), "white")
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                image.putpixel((x, y), color)
    path = tmp_path / name
    image.save(path)
    return path


def test_identical_pages_score_one(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0), (10, 10, 50, 50))
    b = _png(tmp_path, "b.png", (0, 0, 0), (10, 10, 50, 50))
    assert page_similarity(a, b) == pytest.approx(1.0)


def test_a_small_text_change_stays_above_the_gate(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0), (10, 10, 50, 50))
    b = _png(tmp_path, "b.png", (0, 0, 0), (10, 10, 58, 50))
    assert page_similarity(a, b) > 0.95


def test_a_wholly_different_page_scores_low(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0), (0, 0, 200, 200))
    b = _png(tmp_path, "b.png", (0, 0, 0), (0, 0, 1, 1))
    assert page_similarity(a, b) < 0.5


def test_differently_sized_pages_score_zero(tmp_path):
    a = _png(tmp_path, "a.png", (0, 0, 0), (10, 10, 50, 50))
    b = tmp_path / "b.png"
    Image.new("RGB", (100, 100), "white").save(b)
    assert page_similarity(a, b) == 0.0
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/integration/test_translate_visual_similarity.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/docs/domain/visual_similarity.py
"""Measure how much two rendered pages differ.

"The translated PDF looks like the original" is the headline promise of this
capability, and a promise nobody measures is a promise nobody keeps. The
existing `PdfRenderPort.render_pages` already rasterizes pages to PNG, so the
gate costs one comparison: render both, diff them, score them.

# ponytail: mean absolute pixel difference, not SSIM. It is enough to catch
# the failures that matter here -- a page that lost its images, a block that
# escaped its box, a layout that collapsed -- and it needs no scikit-image.
# Upgrade to SSIM only if a real document scores well while looking wrong.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops


def page_similarity(before_png: Path, after_png: Path) -> float:
    """Return similarity in `[0.0, 1.0]`, where 1.0 is pixel-identical.

    Pages of different sizes score 0.0: a page-geometry change is a total
    failure of the promise, not a small difference to average away.
    """
    with Image.open(before_png) as before_image, Image.open(after_png) as after_image:
        before = before_image.convert("L")
        after = after_image.convert("L")
        if before.size != after.size:
            return 0.0
        difference = ImageChops.difference(before, after)
        histogram = difference.histogram()
        total = sum(histogram)
        if total == 0:
            return 1.0
        mean = sum(value * count for value, count in enumerate(histogram)) / total
        return 1.0 - (mean / 255.0)
```

- [ ] **Step 4: Add the end-to-end gate test**

```python
# append to tests/integration/test_translate_visual_similarity.py
def test_a_translated_pdf_stays_visually_close_to_its_original(tmp_path):
    """The headline promise, as a number CI can fail on."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt

    from docs.domain.block_grouping import group_runs_into_blocks
    from docs.domain.text_fitting import fit_text_to_block
    from docs.infrastructure.pdf.pdfium2_pdf_render_adapter import Pdfium2PdfRenderAdapter
    from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import (
        BlockReplacement,
        Pypdfium2TextEditAdapter,
    )

    figure = plt.figure(figsize=(6, 4))
    figure.text(0.1, 0.8, "Hello world", fontsize=18)
    figure.text(0.1, 0.6, "Second line of text", fontsize=12)
    original = tmp_path / "original.pdf"
    figure.savefig(original)
    plt.close(figure)

    editor = Pypdfium2TextEditAdapter()
    mapping = {"Hello world Second line of text": "Hola mundo Segunda linea de texto"}
    replacements = [
        BlockReplacement(
            page=block.page,
            remove=block.runs,
            fitted=fit_text_to_block(mapping.get(block.text, block.text), block),
            x=block.x,
            top=block.top,
        )
        for block in group_runs_into_blocks(editor.read_runs(original))
    ]
    translated = tmp_path / "translated.pdf"
    editor.write_blocks(original, translated, replacements)

    renderer = Pdfium2PdfRenderAdapter()
    before = renderer.render_pages(original, tmp_path / "before", autotrim=False)
    after = renderer.render_pages(translated, tmp_path / "after", autotrim=False)
    assert len(before) == len(after), "page count changed"
    assert page_similarity(before[0], after[0]) >= 0.95
```

- [ ] **Step 5: Run tests and confirm they pass**

Run: `uv run pytest tests/integration/test_translate_visual_similarity.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
rtk git add src/docs/domain/visual_similarity.py tests/integration/test_translate_visual_similarity.py
rtk git commit -m "feat(translate): mechanical visual-similarity gate for layout preservation"
```

---

## Task 11: Mechanise the `/ID` normalizer invariant

`normalize_docx_zip_timestamps` is enforced by an architecture test rather than
by discipline. The PDF normalizer gets the same treatment, for the same reason:
a future writer that forgets it produces a "flaky" test and a real bug.

**Files:**
- Create: `tests/architecture/test_pdf_writer_invariant.py`

- [ ] **Step 1: Write the test**

```python
# tests/architecture/test_pdf_writer_invariant.py
"""Every module that saves a PDF must end in `normalize_pdf_id`.

PDFium stamps a random trailer `/ID` on every save, so a writer that skips the
normalizer produces different bytes for identical input. That reads as a flaky
byte-identity test and IS a determinism bug. This mirrors
`test_docx_writer_invariant.py`, needs no graph index, and therefore never
skips.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "docs"
_SAVE_CALLS = {"save", "write_bytes"}
_NORMALIZER = "normalize_pdf_id"


def _pdf_saving_modules() -> list[Path]:
    found = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "pypdfium2" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SAVE_CALLS
            ):
                found.append(path)
                break
    return found


def test_the_scan_finds_at_least_one_pdf_writer():
    """Probe against a vacuous pass: a scan that stops matching would
    otherwise report zero violations forever."""
    assert _pdf_saving_modules(), "the PDF-writer scan matched nothing; it is broken"


def test_every_pdf_writer_routes_through_the_id_normalizer():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in _pdf_saving_modules()
        if _NORMALIZER not in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"these modules save a PDF without {_NORMALIZER}: {offenders}. "
        "PDFium writes a random trailer /ID on save; skipping the normalizer "
        "makes output non-deterministic (design.md ADR-3)."
    )
```

- [ ] **Step 2: Run it and confirm it passes**

Run: `uv run pytest tests/architecture/test_pdf_writer_invariant.py -v`
Expected: 2 passed (Task 4's adapter already calls the normalizer)

- [ ] **Step 3: Verify it actually catches a violation**

Temporarily delete the `normalize_pdf_id` call from
`pypdfium2_text_edit_adapter.py`, re-run, confirm `test_every_pdf_writer_routes_through_the_id_normalizer`
FAILS, then restore the call.

- [ ] **Step 4: Commit**

```bash
rtk git add tests/architecture/test_pdf_writer_invariant.py
rtk git commit -m "test(arch): mechanise the PDF /ID normalizer invariant"
```

---

## Task 12: Capability spec and documentation

**Files:**
- Create: `openspec/specs/document-translate/spec.md`
- Modify: `AGENTS.md` — document the `docs translate` command
- Modify: `CLAUDE.md` — add the two PDFium gotchas to the determinism section

- [ ] **Step 1: Write the capability spec**

Follow the shape of `openspec/specs/document-ingest/spec.md`: a `## Purpose`
section naming the implementing classes and ports, then `## Requirements` with
`### Requirement:` headings and `#### Scenario:` GIVEN/WHEN/THEN blocks.

Required requirements, each traceable to a task above:

1. **Unconditional Translation** — the system MUST NOT gate translation on
   content, topic or provenance; a model refusal MUST degrade a single block
   and MUST NOT abort the run. (Task 6, Task 8)
2. **Layout Preservation** — page count, page geometry, images and vector art
   MUST be unchanged; translated text MUST be laid out within its source
   block's bounding box. (Task 3, Task 4)
3. **Deterministic Output** — two runs over identical input with a warm
   translation memory MUST produce byte-identical PDFs. (Task 1, Task 5)
4. **Honest Degradation** — untranslated blocks, overflowed blocks,
   substituted fonts and untrusted multi-column pages MUST each be counted and
   reported in the command's own output line. (Task 8)
5. **No Text Layer** — a scanned or image-based PDF MUST be refused with a
   message naming OCR as the remedy, never silently half-translated. (Task 7)
6. **Visual Fidelity** — rendered page similarity between source and output
   MUST be at least 0.95. (Task 10)

`tests/architecture/test_spec_symbol_references.py` requires at least three
real backticked symbols. Use `TranslateService`, `guarded_translate`,
`normalize_pdf_id`, `group_runs_into_blocks`, `fit_text_to_block`,
`page_similarity`.

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest && uv run ruff check . && uv run mypy`
Expected: all green, including `tests/unit/test_agents_md_content.py`
(which fails if `AGENTS.md` documents a command that does not exist) and
`tests/architecture/test_spec_symbol_references.py`

- [ ] **Step 3: Rebuild the spec-to-code bridge**

```bash
graphify update . && uv run python tools/spec_code_bridge.py
```

- [ ] **Step 4: Commit**

```bash
rtk git add openspec/specs/document-translate/ AGENTS.md CLAUDE.md
rtk git commit -m "docs(translate): capability spec and PDFium determinism gotchas"
```

---

## Definition of done

- [ ] `uv run pytest` green, coverage at or above the 93% CI floor
- [ ] `uv run ruff check .` and `uv run mypy` both clean
- [ ] `docs translate sample.pdf --to es` produces a readable, correctly laid-out PDF
- [ ] Running it twice produces byte-identical files
- [ ] A deliberately refusing translation engine still produces a complete document
- [ ] A scanned PDF is refused with a message naming OCR
- [ ] Visual similarity on the sample is at or above 0.95

## Deliberately out of scope

Named so Phase 1 does not design them out, and so nobody mistakes their absence
for an oversight:

- **Multi-column reading order** (Phase 2) — `pages_with_columns` reports them
  as untrusted rather than pretending.
- **OCR for scanned PDFs** (Phase 3) — refused with a clear reason today.
- **Non-Latin target scripts** — base-14 fonts have no Cyrillic, CJK or Arabic
  coverage. Needs a bundled Noto face, which is a licensing decision.
- **Tables and forms** — treated as ordinary text blocks; cell boundaries are
  not respected.
- **Other input formats** (Phase 4) — `TranslationPort` and the translation
  memory are format-agnostic by design and will be reused unchanged.
