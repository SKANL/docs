# tests/unit/domain/test_sections.py
from pathlib import Path

from docs.domain.sections import apply_stamp, default_section_metadata, infer_section_id_from_path, with_frontmatter


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


def test_with_frontmatter_formats_metadata_and_body():
    text = with_frontmatter("# Cuerpo\n", {"b": 2, "a": 1})
    assert text.startswith("---\n")
    assert '"a": 1' in text
    assert text.index('"a"') < text.index('"b"')  # sort_keys=True
    assert text.endswith("---\n# Cuerpo\n")


def test_default_section_metadata_shape():
    metadata = default_section_metadata("introduccion", "Introducción")
    assert metadata == {
        "managed_by": "tesina-harness",
        "schema": 3,
        "section_id": "introduccion",
        "title": "Introducción",
    }


def test_apply_stamp_synthesizes_default_metadata_when_empty():
    result = apply_stamp(
        metadata={},
        section_id="introduccion",
        title="Introducción",
        body="texto",
        body_hash="b" * 64,
        authored_by="agent-x",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["managed_by"] == "tesina-harness"
    assert result["schema"] == 3
    assert result["section_id"] == "introduccion"
    assert result["title"] == "Introducción"
    assert result["authored_by"] == "agent-x"
    assert result["body_hash"] == "b" * 64
    assert result["stamped_at"] == "2026-06-21T00:00:00"
    assert "model" not in result


def test_apply_stamp_preserves_existing_metadata_fields():
    existing = {"managed_by": "tesina-harness", "schema": 3, "section_id": "introduccion", "title": "Introducción", "custom": "kept"}
    result = apply_stamp(
        metadata=existing,
        section_id="introduccion",
        title="Introducción",
        body="texto",
        body_hash="c" * 64,
        authored_by="agent-y",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["custom"] == "kept"
    assert result["authored_by"] == "agent-y"


def test_apply_stamp_sets_model_when_provided():
    result = apply_stamp(
        metadata={"managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X"},
        section_id="x",
        title="X",
        body="texto",
        body_hash="d" * 64,
        authored_by="agent-z",
        model="opus",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["model"] == "opus"


def test_apply_stamp_empty_model_does_not_delete_existing_model_key():
    existing = {"managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X", "model": "previous-model"}
    result = apply_stamp(
        metadata=existing,
        section_id="x",
        title="X",
        body="texto",
        body_hash="e" * 64,
        authored_by="agent-w",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["model"] == "previous-model"


def test_apply_stamp_always_overwrites_body_hash_and_stamped_at():
    existing = {
        "managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X",
        "body_hash": "stale", "stamped_at": "2020-01-01T00:00:00",
    }
    result = apply_stamp(
        metadata=existing,
        section_id="x",
        title="X",
        body="nuevo texto",
        body_hash="f" * 64,
        authored_by="agent-v",
        model="",
        stamped_at="2026-06-21T12:00:00",
    )
    assert result["body_hash"] == "f" * 64
    assert result["stamped_at"] == "2026-06-21T12:00:00"
