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


def test_a_heading_does_not_absorb_the_paragraph_below_it():
    """A block draws at its LARGEST font size, so merging a 24pt heading with
    the 11pt body under it renders the whole paragraph at heading size. That
    shipped a page of giant overlapping text on a real book."""
    runs = [
        _run("Introduccion", 62.0, 700.0, w=120.0, h=24.0, size=24.0),
        _run("Tratar de aprender de las conversaciones", 62.0, 676.0, w=240.0, h=11.0, size=11.0),
    ]
    blocks = group_runs_into_blocks(runs)
    assert len(blocks) == 2
    assert blocks[0].font_size == 24.0
    assert blocks[1].font_size == 11.0


def test_lines_of_the_same_size_still_form_one_paragraph():
    """The size-change rule must not shatter ordinary body text."""
    runs = [
        _run("primera linea del parrafo", 62.0, 700.0, w=200.0, h=11.0, size=11.0),
        _run("segunda linea del parrafo", 62.0, 687.0, w=200.0, h=11.0, size=11.0),
    ]
    assert len(group_runs_into_blocks(runs)) == 1


def test_a_small_size_difference_does_not_split_a_paragraph():
    """Real documents jitter by a fraction of a point; only a real change of
    type size is a boundary."""
    runs = [
        _run("primera linea", 62.0, 700.0, w=200.0, h=11.0, size=11.0),
        _run("segunda linea", 62.0, 687.0, w=200.0, h=11.2, size=11.2),
    ]
    assert len(group_runs_into_blocks(runs)) == 1


def test_emphasis_stays_inside_its_sentence():
    """`Baskerville` and `Baskerville-Italic` are the same TYPEFACE. Treating
    them as different families cut every sentence apart at each italicised
    word: "We know we ought to talk to customers" became "We know we",
    "ought" and the rest, which destroyed the sentence for the translator and
    made the fragments overlap when redrawn."""
    runs = [
        _run("We know we ", 72.0, 700.0, w=60.0, size=14.0),
        _run("ought", 133.0, 700.0, w=30.0, size=14.0),
        _run(" to talk to customers", 164.0, 700.0, w=110.0, size=14.0),
    ]
    runs = [
        TextRun(r.text, r.x, r.y, r.width, r.height, r.page, r.font_size, family)
        for r, family in zip(
            runs, ["Baskerville", "Baskerville-Italic", "Baskerville"], strict=True
        )
    ]
    blocks = group_runs_into_blocks(runs)
    assert len(blocks) == 1
    assert blocks[0].text == "We know we ought to talk to customers"


def test_a_different_typeface_still_ends_a_block():
    """A monospace label beside serif dialogue is a change of ROLE."""
    runs = [
        TextRun("Son:", 72.0, 700.0, 30.0, 10.0, 0, 14.0, "Courier"),
        TextRun("Hola", 110.0, 700.0, 40.0, 10.0, 0, 14.0, "Baskerville"),
    ]
    assert {b.text for b in group_runs_into_blocks(runs)} == {"Son:", "Hola"}


def test_the_first_line_keeps_its_own_start_under_a_hanging_indent():
    """Line 0 began right of the block's leftmost edge; redrawing it at `x`
    slid it into the dialogue label beside it."""
    runs = [
        TextRun("primera linea", 235.0, 700.0, 200.0, 10.0, 0, 14.0, "Baskerville"),
        TextRun("continuacion", 185.0, 686.0, 200.0, 10.0, 0, 14.0, "Baskerville"),
    ]
    block = group_runs_into_blocks(runs)[0]
    assert block.x == 185.0
    assert block.first_line_x == 235.0


def test_first_line_x_equals_x_without_a_hanging_indent():
    runs = [_run("una linea", 72.0, 700.0, w=200.0)]
    block = group_runs_into_blocks(runs)[0]
    assert block.first_line_x == block.x


def _line(text, y, x=72.0, size=14.0, w=400.0):
    return TextRun(text, x, y, w, size * 0.7, 0, size, "Baskerville")


def test_paragraphs_separate_on_baseline_step_not_ink_gap():
    """Measured on a real page: lines within a paragraph stepped 16pt and
    paragraphs were separated by 32pt -- exactly double -- yet the ink-gap
    rule computed 19.2 against a 20.5 threshold and merged eight short
    paragraphs into three, leaving huge blank gaps and a paragraph running
    past the right margin."""
    runs = [
        _line("primera linea del parrafo uno", 700.0),
        _line("segunda linea del parrafo uno", 684.0),
        _line("primera linea del parrafo dos", 652.0),
        _line("segunda linea del parrafo dos", 636.0),
        _line("primera linea del parrafo tres", 604.0),
        _line("segunda linea del parrafo tres", 588.0),
    ]
    blocks = group_runs_into_blocks(runs)
    assert len(blocks) == 3, [b.text for b in blocks]


def test_generous_leading_does_not_split_a_paragraph():
    """A body paragraph stepping 22pt at 14pt type is leading, not a break --
    its italic runs sit ~3pt lower than the roman ones on the same visual
    line, which stretches the measured step."""
    runs = [
        _line("We know we ought to talk to customers", 114.6),
        _line("But we still end up building stuff nobody buys", 92.2),
        _line("people is meant to prevent?", 73.0),
    ]
    assert len(group_runs_into_blocks(runs)) == 1


def test_line_spacing_is_the_smallest_repeating_step():
    """A page of two-line paragraphs ties the line step against the paragraph
    step, and picking the most common one returned the 32pt PARAGRAPH step as
    the line spacing -- which merged an entire page into a single block."""
    from docs.domain.block_grouping import _lines, modal_line_spacing

    runs = [_line(f"linea {n}", y) for n, y in enumerate([700.0, 684.0, 652.0, 636.0, 604.0, 588.0])]
    assert modal_line_spacing(_lines(runs)) == 16.0


def test_too_few_lines_yields_no_measured_spacing():
    from docs.domain.block_grouping import _lines, modal_line_spacing

    assert modal_line_spacing(_lines([_line("una", 700.0), _line("dos", 684.0)])) is None


def _styled_run(text, x, y, family, size=14.0):
    return TextRun(text, x, y, len(text) * 6.0, size * 0.7, 0, size, family)


def test_a_mostly_italic_block_is_drawn_italic():
    """A short roman quote followed by long italic commentary is italic. The
    first run says roman, and the first run is not the block."""
    runs = [
        _styled_run("“Yes.” ", 72.0, 700.0, "Baskerville"),
        _styled_run("You led me to this answer, so here you go.", 110.0, 700.0, "Baskerville-Italic"),
    ]
    assert group_runs_into_blocks(runs)[0].italic is True


def test_one_emphasised_word_does_not_italicise_a_sentence():
    runs = [
        _styled_run("We know we ", 72.0, 700.0, "Baskerville"),
        _styled_run("ought", 140.0, 700.0, "Baskerville-Italic"),
        _styled_run(" to talk to customers regularly", 180.0, 700.0, "Baskerville"),
    ]
    assert group_runs_into_blocks(runs)[0].italic is False


def test_the_baseline_is_the_runs_own_y_not_derived_from_the_ink_top():
    runs = [_run("una linea", 72.0, 700.0, w=200.0, h=12.8, size=14.0)]
    block = group_runs_into_blocks(runs)[0]
    assert block.baseline == 700.0
    assert block.baseline != block.top - block.font_size


def test_line_spacing_is_measured_from_the_blocks_own_baselines():
    runs = [
        _run("primera", 72.0, 700.0, w=200.0, h=10.0, size=14.0),
        _run("segunda", 72.0, 684.0, w=200.0, h=10.0, size=14.0),
    ]
    assert group_runs_into_blocks(runs)[0].line_spacing == 16.0


def test_a_single_line_block_has_no_measured_spacing():
    assert group_runs_into_blocks([_run("sola", 72.0, 700.0)])[0].line_spacing is None


def test_a_bare_majority_of_italic_is_not_enough():
    """A simple majority rendered a whole page in italics: a quote followed by
    longer italic commentary is majority-italic. A page of italics reads far
    worse than a page of roman with its emphasis flattened."""
    runs = [
        _styled_run("Una frase citada bastante larga en redonda", 72.0, 700.0, "Baskerville"),
        _styled_run("y un comentario italico algo mas largo aun aqui", 340.0, 700.0, "Baskerville-Italic"),
    ]
    assert group_runs_into_blocks(runs)[0].italic is False


def test_leading_ignores_the_baseline_offset_of_italic_runs():
    """Italic runs sit ~3pt below the roman ones on the SAME visual line.
    Taking the minimum RAW baseline step turned that offset into the leading
    and stacked every line of a page on top of the one above it."""
    runs = [
        _styled_run("primera linea en redonda", 72.0, 700.0, "Baskerville"),
        _styled_run("con enfasis", 260.0, 696.8, "Baskerville-Italic"),
        _styled_run("segunda linea del parrafo", 72.0, 684.0, "Baskerville"),
    ]
    assert group_runs_into_blocks(runs)[0].line_spacing == 16.0


def test_a_two_line_block_is_not_mistaken_for_justified():
    """With two lines the comparison is one value against itself, so the
    spread is trivially zero. That stretched a centred chapter title across
    the column with a hole in the middle."""
    runs = [
        _styled_run("Asking important", 100.0, 700.0, "Optima-Bold", size=36.0),
        _styled_run("questions", 240.0, 640.0, "Optima-Bold", size=36.0),
    ]
    assert group_runs_into_blocks(runs)[0].justified is False


def test_three_flush_lines_are_justified():
    runs = [
        TextRun("primera linea llena", 72.0, 700.0, 451.0, 10.0, 0, 14.0, "Baskerville"),
        TextRun("segunda linea llena", 72.0, 684.0, 451.0, 10.0, 0, 14.0, "Baskerville"),
        TextRun("ultima corta", 72.0, 668.0, 120.0, 10.0, 0, 14.0, "Baskerville"),
    ]
    assert group_runs_into_blocks(runs)[0].justified is True


def test_a_centred_heading_is_detected_from_its_lines():
    """The block's BOX spans nearly the whole column once both lines are
    enclosed, so a box-based test calls it left-aligned and drops the short
    second line against the left margin."""
    runs = [
        TextRun("Asking important", 100.0, 700.0, 627.0, 25.0, 0, 36.0, "Optima-Bold"),
        TextRun("questions", 240.0, 640.0, 350.0, 25.0, 0, 36.0, "Optima-Bold"),
    ]
    assert group_runs_into_blocks(runs)[0].centered is True


def test_flush_lines_are_not_called_centred():
    runs = [
        TextRun("primera linea igual", 72.0, 700.0, 451.0, 10.0, 0, 14.0, "Baskerville"),
        TextRun("segunda linea igual", 72.0, 684.0, 451.0, 10.0, 0, 14.0, "Baskerville"),
    ]
    assert group_runs_into_blocks(runs)[0].centered is False
