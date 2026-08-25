from docs.domain.block_grouping import TextBlock, TextRun
from docs.domain.collision import collides, drawn_bottom
from docs.domain.text_fitting import FittedText


def _block(y, x=72.0, width=400.0, size=14.0, lines=1, spacing=16.0):
    runs = [
        TextRun(f"linea {n}", x, y - n * spacing, width, size * 0.7, 0, size, "Baskerville")
        for n in range(lines)
    ]
    return TextBlock(runs=runs)


def _fitted(count, size=14.0):
    return FittedText([f"linea {n}" for n in range(count)], size, False, 0.5)


def test_a_block_that_keeps_its_line_count_collides_with_nothing():
    upper, lower = _block(700.0), _block(668.0)
    assert collides([(upper, _fitted(1)), (lower, _fitted(1))]) == []


def test_a_block_that_grows_into_the_one_below_is_reported():
    upper, lower = _block(700.0), _block(668.0)
    assert collides([(upper, _fitted(4)), (lower, _fitted(1))]) == [upper]


def test_blocks_on_the_same_visual_line_are_not_a_collision():
    """A dialogue label and the speech beside it have legitimately
    overlapping boxes and baselines a fraction of a point apart. Counting
    those reported 90 collisions on a book that had 3."""
    label = _block(700.0, x=108.0, width=42.0)
    speech = _block(699.6, x=126.0, width=397.0)
    assert collides([(label, _fitted(1)), (speech, _fitted(3))]) == []


def test_blocks_that_do_not_share_a_column_never_collide():
    left, right = _block(700.0, x=40.0, width=60.0), _block(600.0, x=300.0, width=200.0)
    assert collides([(left, _fitted(10)), (right, _fitted(1))]) == []


def test_blocks_on_different_pages_never_collide():
    upper = _block(700.0)
    lower = TextBlock(runs=[TextRun("otra", 72.0, 668.0, 400.0, 9.8, 1, 14.0, "Baskerville")])
    assert collides([(upper, _fitted(6)), (lower, _fitted(1))]) == []


def test_an_empty_layout_collides_with_nothing():
    block = _block(700.0)
    assert collides([(block, FittedText([], 14.0, False, 0.5))]) == []


def test_descenders_alone_are_not_a_collision():
    """The last baseline hangs a little below itself; that is a descender, not
    text landing on the block underneath."""
    upper, lower = _block(700.0), _block(684.0)
    assert collides([(upper, _fitted(1)), (lower, _fitted(1))]) == []


def test_the_drawn_bottom_uses_the_blocks_measured_leading():
    block = _block(700.0, lines=2, spacing=16.0)
    assert block.line_spacing == 16.0
    assert drawn_bottom(block, _fitted(3)) == 700.0 - 2 * 16.0 - 14.0 * 0.25
