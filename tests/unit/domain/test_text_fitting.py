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


def test_every_returned_line_is_non_empty():
    fitted = fit_text_to_block("uno dos tres cuatro cinco seis", _block(50.0, 100.0))
    assert all(line.strip() for line in fitted.lines)


def test_no_word_is_lost_while_wrapping():
    text = "uno dos tres cuatro cinco seis siete ocho"
    fitted = fit_text_to_block(text, _block(50.0, 200.0))
    assert " ".join(fitted.lines).split() == text.split()


def test_the_calibration_divides_by_characters_per_line():
    """`width` is the width of ONE line. Dividing it by the characters of ALL
    lines halves a two-line block's ratio, and the estimator then packs twice
    as much onto each line and runs off the right margin."""
    from docs.domain.text_fitting import measured_advance_ratio

    one_line = measured_advance_ratio("x" * 40, 200.0, 10.0, line_count=1)
    two_lines = measured_advance_ratio("x" * 80, 200.0, 10.0, line_count=2)
    assert one_line == two_lines


def test_a_translated_line_never_exceeds_its_box(): 
    """The end-to-end symptom of that bug: text running past the margin."""
    from docs.domain.text_fitting import fit_text_to_block

    block = TextBlock(runs=[
        TextRun("una linea de texto de ejemplo aqui", 0.0, 20.0, 200.0, 10.0, 0, 10.0),
        TextRun("y una segunda linea del mismo bloque", 0.0, 8.0, 200.0, 10.0, 0, 10.0),
    ])
    fitted = fit_text_to_block("palabra " * 20, block)
    assert all(fitted.line_width(line) <= block.width + 1 for line in fitted.lines)


def test_a_wider_column_lets_a_long_line_stay_on_one_line():
    """A single-line block's right edge is merely where its text stopped. A
    heading whose translation is longer may use the rest of the column instead
    of dropping a second line onto the text beneath it."""
    from docs.domain.text_fitting import fit_text_to_block

    block = TextBlock(runs=[TextRun("Passing the mom test", 108.0, 700.0, 292.0, 25.0, 0, 36.0)])
    narrow = fit_text_to_block("Como aprobar el test de la mama", block)
    wide = fit_text_to_block("Como aprobar el test de la mama", block, max_width=523.0)
    assert len(narrow.lines) > len(wide.lines)
    assert len(wide.lines) == 1


def test_max_height_forces_a_shrink_rather_than_a_second_line():
    from docs.domain.text_fitting import fit_text_to_block

    block = TextBlock(runs=[TextRun("Titulo", 72.0, 700.0, 300.0, 25.0, 0, 36.0)])
    cramped = fit_text_to_block("Un titulo bastante mas largo que el original", block, max_height=20.0)
    assert cramped.font_size < 36.0
