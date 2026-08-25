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
