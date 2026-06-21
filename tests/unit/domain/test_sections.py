# tests/unit/domain/test_sections.py
from pathlib import Path

from docs.domain.sections import infer_section_id_from_path


def test_infer_section_id_strips_leading_digits_and_hyphen():
    path = Path("/repo/sections/001-introduccion.md")
    assert infer_section_id_from_path(path) == "introduccion"


def test_infer_section_id_strips_multi_digit_order():
    path = Path("/repo/sections/012-metodologia.md")
    assert infer_section_id_from_path(path) == "metodologia"


def test_infer_section_id_leaves_id_unchanged_when_no_leading_digits():
    path = Path("/repo/sections/referencias.md")
    assert infer_section_id_from_path(path) == "referencias"


def test_infer_section_id_only_strips_one_leading_digit_run():
    # Legacy regex `^\d+-` only matches a single leading run-of-digits-then-hyphen;
    # a section id that itself starts with digits after the order prefix is
    # preserved verbatim (no second strip pass).
    path = Path("/repo/sections/003-2024-resultados.md")
    assert infer_section_id_from_path(path) == "2024-resultados"


def test_infer_section_id_ignores_file_extension():
    path = Path("/repo/sections/005-conclusiones.md")
    assert infer_section_id_from_path(path) == "conclusiones"
