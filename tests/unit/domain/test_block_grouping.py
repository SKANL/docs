from docs.domain.block_grouping import TextRun, group_runs_into_blocks


def _run(text, x, y, w=50.0, h=10.0, page=0, size=12.0):
    return TextRun(text=text, x=x, y=y, width=w, height=h, page=page, font_size=size)


def test_runs_on_the_same_baseline_join_left_to_right():
    # x=64 leaves a 4pt gap after "Hello" (10..60) -- a real inter-word space.
    # Butting the runs together at x=60 would mean a ZERO gap, which in a real
    # PDF is a split word, not two words; that case is covered below.
    blocks = group_runs_into_blocks([_run("world", 64.0, 700.0), _run("Hello", 10.0, 700.0)])
    assert len(blocks) == 1
    assert blocks[0].text == "Hello world"


def test_touching_runs_rejoin_without_a_space():
    """A ligature arrives split: "fl" + "at" must read "flat", not "fl at".
    Measured on a real PDF -- matplotlib emits exactly this."""
    runs = [
        _run("Costs remained ", 61.82, 585.92, w=85.37, size=11.0),
        _run("fl", 150.93, 586.08, w=5.66, size=11.0),
        _run("at compared to last year.", 158.26, 583.78, w=136.37, size=11.0),
    ]
    assert group_runs_into_blocks(runs)[0].text == "Costs remained flat compared to last year."


def test_a_line_whose_baseline_drifts_keeps_its_reading_order():
    """A fixed 2.0pt tolerance split this real line in two and emitted
    "fi nance team Prepared by the" -- the words in the WRONG ORDER."""
    runs = [
        _run("fi", 152.74, 681.12, w=5.66, size=11.0),
        _run("nance team", 160.40, 680.96, w=63.60, size=11.0),
        _run("Prepared by the ", 62.28, 678.82, w=86.72, size=11.0),
    ]
    assert group_runs_into_blocks(runs)[0].text == "Prepared by the finance team"


def test_widely_spaced_runs_on_one_baseline_are_separate_blocks():
    """Chart axis labels share a baseline but are 32pt apart. Merging them
    into one block redraws all seven left-aligned in the corner."""
    runs = [_run(f"{n}.0", 68.25 + n * 46.0, 104.05, w=14.14, size=8.0) for n in range(4)]
    blocks = group_runs_into_blocks(runs)
    assert len(blocks) == 4


def test_lines_that_do_not_overlap_horizontally_stay_separate():
    """A chart title at x=189 merged with an axis label at x=39 purely
    because their baselines were close."""
    runs = [
        _run("Revenue", 189.22, 362.22, w=50.51, size=11.0),
        _run("7.0", 39.13, 341.65, w=14.41, size=8.0),
    ]
    assert {b.text for b in group_runs_into_blocks(runs)} == {"Revenue", "7.0"}


def test_repeated_whitespace_is_collapsed():
    """Runs carry their own trailing spaces; combined with the separator they
    would change the block's identity, and therefore its cache key, invisibly."""
    runs = [_run("Prepared by the ", 10.0, 700.0, w=50.0), _run("team", 64.0, 700.0)]
    assert "  " not in group_runs_into_blocks(runs)[0].text


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
    # The two lines must OVERLAP horizontally to belong to one block: runs at
    # x=10..30 and x=100..130 share no column and are two blocks by design.
    runs = [_run("a", 10.0, 700.0, w=120.0, h=10.0), _run("b", 100.0, 686.0, w=30.0, h=10.0)]
    block = group_runs_into_blocks(runs)[0]
    assert (block.x, block.right, block.bottom, block.top) == (10.0, 130.0, 686.0, 710.0)


def test_no_runs_yields_no_blocks():
    assert group_runs_into_blocks([]) == []


def test_the_largest_run_sets_the_block_font_size():
    runs = [_run("Big", 10.0, 700.0, size=18.0), _run("small", 60.0, 700.0, size=9.0)]
    assert group_runs_into_blocks(runs)[0].font_size == 18.0


def test_a_run_carries_its_font_family_when_one_is_known():
    run = TextRun("x", 0.0, 0.0, 10.0, 10.0, 0, 12.0, font_family="DejaVuSans")
    assert run.font_family == "DejaVuSans"


def test_font_family_defaults_to_empty_for_pure_geometry_callers():
    assert _run("x", 0.0, 0.0).font_family == ""
