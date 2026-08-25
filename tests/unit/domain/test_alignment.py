from docs.domain.alignment import Alignment, Column, detect_alignment, detect_column

# The measured column of a real book page: body text ran 72 -> 523.
COLUMN = Column(72.0, 523.0)


def test_the_dominant_edges_define_the_column():
    lefts = [72.2, 72.2, 72.0, 72.0, 72.3, 137.5, 225.5]
    rights = [523.0, 523.0, 523.0, 523.1, 523.0, 459.4, 521.6]
    assert detect_column(lefts, rights) == Column(72.0, 523.0)


def test_a_page_with_no_blocks_has_no_column():
    assert detect_column([], []) is None


def test_a_column_whose_right_precedes_its_left_is_rejected():
    """Guessing a column from scattered fragments would misalign every block
    on the page. No column is safer than a wrong one."""
    assert detect_column([500.0], [100.0]) is None


def test_a_full_width_paragraph_is_left_aligned():
    assert detect_alignment(72.0, 523.0, COLUMN) is Alignment.LEFT


def test_a_narrow_block_centred_in_the_column_is_centred():
    """The measured heading: x=137.5, right=459.4, midpoint 298.5 against the
    column's 297.5."""
    assert detect_alignment(137.5, 459.4, COLUMN) is Alignment.CENTER


def test_a_block_touching_the_right_margin_only_is_right_aligned():
    assert detect_alignment(400.0, 523.0, COLUMN) is Alignment.RIGHT


def test_a_block_starting_at_the_left_margin_is_left_aligned():
    """Even a short one whose midpoint happens to land near the centre: its
    next line would start at the margin, so that is where it belongs."""
    assert detect_alignment(72.0, 200.0, COLUMN) is Alignment.LEFT


def test_an_indented_block_touching_neither_margin_is_left_aligned():
    """A block hanging off-centre is not evidence of centring, and left moves
    the text the least when we are unsure."""
    assert detect_alignment(120.0, 300.0, COLUMN) is Alignment.LEFT


def test_without_a_column_everything_is_left_aligned():
    assert detect_alignment(137.5, 459.4, None) is Alignment.LEFT


def test_a_degenerate_column_falls_back_to_left():
    assert detect_alignment(10.0, 20.0, Column(50.0, 50.0)) is Alignment.LEFT
