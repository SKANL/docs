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


def test_base14_covers_latin_targets():
    """Spanish, French, German and Portuguese all fit cp1252, so translating
    into them never needs a megabyte of embedded font."""
    from docs.domain.fonts import needs_embedded_font

    assert needs_embedded_font("canción, año, ¿qué? ¡Sí!") is False
    assert needs_embedded_font("Grüße, café, ação") is False


def test_non_latin_targets_require_a_real_font():
    """A base-14 face renders Cyrillic and Greek as empty boxes: not a
    degraded document, a destroyed one."""
    from docs.domain.fonts import needs_embedded_font

    assert needs_embedded_font("привет мир") is True
    assert needs_embedded_font("γεια σου") is True


def test_a_label_gutter_does_not_become_the_right_margin():
    """Eight dialogue labels ending at the same x outvote the body text under
    a mode, and page 10 of a real book detected its column as 72 -> 142: the
    speaker gutter, not the text. A heading was then never widened past it
    and dropped its second line onto the dialogue below.

    A margin is an edge that REPEATS, and the right margin is the furthest
    such edge -- so a repeated short edge can no longer outvote a repeated
    long one.
    """
    labels = [141.6] * 8
    body = [337.5, 398.4, 481.1, 519.5, 522.1, 522.4]
    column = detect_column([74.6] + [108.1] * 8 + [126.4] * 5, labels + body)
    assert column is not None
    assert column.right == 522.0


def test_a_lone_edge_past_the_margin_does_not_set_it():
    """A single block bleeding past the margin -- a long URL, a wide caption
    -- would drag the column with it under a plain maximum, and every other
    block on the page would then be widened into the margin."""
    rights = [523.0, 523.0, 523.1, 611.0]
    assert detect_column([72.0, 72.0, 72.0, 72.0], rights) == Column(72.0, 523.0)


def test_a_wide_block_whose_midpoint_lands_near_the_centre_is_not_centred():
    """A dialogue line filling most of the column has ~27pt of slack per side,
    so a tolerance measured against the COLUMN passes it trivially. Measured
    on a real book: six body paragraphs were classified centred that way, and
    re-centring a translated line of a different length moves it visibly.

    A block that was actually centred splits its slack almost exactly in half
    -- every real centred block on that book was within 1.5% of even, and
    every coincidence was above 2%.
    """
    # 375pt of text in a 451pt column: 65.5pt of slack, split 41/24.
    assert detect_alignment(113.0, 488.0, COLUMN) is Alignment.LEFT


def test_a_block_that_splits_its_slack_evenly_is_centred():
    """A 60pt display title spans 80% of the column and is still centred --
    width alone cannot tell the two apart, only symmetry can."""
    assert detect_alignment(117.5, 477.5, COLUMN) is Alignment.CENTER
