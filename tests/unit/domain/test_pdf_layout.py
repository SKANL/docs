from docs.domain.alignment import Alignment
from docs.domain.pdf_layout import (
    BASE14,
    ObjectSnapshot,
    drop_unmapped,
    line_start,
    line_x,
    match_key,
    missing_expected_lines,
    outside,
    overlaps,
    permitted_bounds,
    strip_subset_tag,
    styled,
    union,
)


class _Fitted:
    font_size = 10.0

    def line_width(self, line: str) -> float:
        return 10.0 * len(line)


class _Run:
    def __init__(self, y: float) -> None:
        self.y = y


class _Replacement:
    def __init__(self, alignment=Alignment.LEFT, x=50.0, first_line_x=0.0, right=150.0, top=700.0, baseline=0.0, remove=()):
        self.alignment, self.x, self.first_line_x = alignment, x, first_line_x
        self.right, self.top, self.baseline, self.remove = right, top, baseline, remove
        self.fitted = _Fitted()


def test_styled_picks_the_base14_face_per_style():
    assert styled(b"Times-Roman", False, False) == b"Times-Roman"
    assert styled(b"Times-Roman", True, False) == b"Times-Bold"
    assert styled(b"Helvetica", False, True) == b"Helvetica-Oblique"
    assert styled(b"Courier", True, True) == b"Courier-BoldOblique"
    assert set(BASE14) == {b"Times-Roman", b"Helvetica", b"Courier"}


def test_line_start_uses_the_hanging_indent_only_on_line_zero():
    r = _Replacement(first_line_x=70.0)
    assert line_start(r, 0) == 70.0
    assert line_start(r, 1) == 50.0
    assert line_start(_Replacement(), 0) == 50.0


def test_line_x_honours_alignment_and_never_stretches_the_last_justified_line():
    assert line_x(_Replacement(Alignment.LEFT), "abcd", 0) == 50.0
    assert line_x(_Replacement(Alignment.JUSTIFY), "abcd", 1) == 50.0
    assert line_x(_Replacement(Alignment.CENTER), "abcd", 0) == 50.0 + (100.0 - 40.0) / 2
    assert line_x(_Replacement(Alignment.RIGHT), "abcd", 0) == 50.0 + 60.0
    assert line_x(_Replacement(Alignment.RIGHT), "x" * 20, 0) == 50.0  # no slack
    assert line_x(_Replacement(Alignment.RIGHT, right=40.0), "a", 0) == 50.0


def test_strip_subset_tag_only_removes_six_uppercase_letters_plus_plus():
    assert strip_subset_tag("GGKEDP+DejaVuSans") == "DejaVuSans"
    assert strip_subset_tag("ggkedp+DejaVuSans") == "ggkedp+DejaVuSans"
    assert strip_subset_tag("ABC+Font") == "ABC+Font"
    assert strip_subset_tag("Plain") == "Plain"


def test_drop_unmapped_removes_control_characters_but_keeps_whitespace():
    assert drop_unmapped("mis\x02interpreted\x01 ok\n") == "misinterpreted ok\n"


def test_outside_and_overlaps_use_the_half_point_tolerance():
    box = (0.0, 0.0, 10.0, 10.0)
    assert not outside((-0.4, 0.0, 10.4, 10.0), box)
    assert outside((-0.6, 0.0, 10.0, 10.0), box)
    assert overlaps(box, (5.0, 5.0, 15.0, 15.0))
    assert not overlaps(box, (9.8, 0.0, 20.0, 10.0))


def test_union_spans_all_bounds():
    assert union([(0, 0, 5, 5), (3, -1, 9, 4)]) == (0, -1, 9, 5)


def test_missing_expected_lines_matches_by_text_once():
    a, b = ObjectSnapshot(0, "x", (0, 0, 1, 1)), ObjectSnapshot(1, "x", (0, 2, 1, 3))
    assert missing_expected_lines((a, b), (ObjectSnapshot(9, "x", (0, 0, 1, 1)),)) == (b,)
    assert missing_expected_lines((a,), ()) == (a,)


def test_permitted_bounds_extends_to_the_hanging_indent_and_ink_descent():
    r = _Replacement(first_line_x=40.0, baseline=690.0, remove=(_Run(680.0),))
    lines = (ObjectSnapshot(0, "t", (0, 685.0, 1, 1)),)
    assert permitted_bounds(r, lines) == (40.0, 680.0 + (-5.0), 150.0, 700.0)
    assert permitted_bounds(_Replacement(remove=(_Run(680.0),)), ())[1] <= 680.0


def test_match_key_rounds_the_position_to_one_decimal():
    assert match_key("a", 1.26, 2.74) == ("a", 1.3, 2.7)


def test_strip_subset_tag_requires_letters_not_just_uppercase_cased_text():
    assert strip_subset_tag("ABC123+Font") == "ABC123+Font"


def test_drop_unmapped_keeps_digits_and_punctuation():
    assert drop_unmapped("a1.\x02,b") == "a1.,b"


def test_overlaps_needs_vertical_as_well_as_horizontal_intersection():
    box = (0.0, 0.0, 10.0, 10.0)
    assert not overlaps(box, (0.0, 9.8, 10.0, 20.0))


def test_missing_expected_lines_compares_text_not_position_or_index():
    a = ObjectSnapshot(0, "x", (0, 0, 1, 1))
    assert missing_expected_lines((a,), (ObjectSnapshot(0, "y", (0, 0, 1, 1)),)) == (a,)


def test_permitted_bounds_baseline_defaults_to_top_minus_font_size():
    r = _Replacement(remove=(_Run(680.0),))  # baseline 0 -> 700 - 10 = 690
    lines = (ObjectSnapshot(0, "t", (0, 685.0, 1, 1)),)
    assert permitted_bounds(r, lines)[1] == 675.0


def test_permitted_bounds_without_removed_runs_starts_from_the_top():
    assert permitted_bounds(_Replacement(), ()) == (50.0, 700.0, 150.0, 700.0)


def test_permitted_bounds_ink_never_descends_below_zero_extension():
    r = _Replacement(baseline=690.0, remove=(_Run(680.0),))
    lines = (ObjectSnapshot(0, "t", (0, 695.0, 1, 1)),)  # sits above the baseline
    assert permitted_bounds(r, lines)[1] == 680.0
