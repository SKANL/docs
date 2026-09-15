from __future__ import annotations

from docs.domain.corrections import parse_simple_yaml


def test_parse_simple_yaml_parses_basic_key_value_pairs():
    text = "id: c1\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_skips_blank_lines_and_comments():
    text = "id: c1\n\n# a comment\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_strips_double_and_single_quotes():
    text = 'find: "hello world"\nreplace: \'bye\'\n'
    assert parse_simple_yaml(text) == {"find": "hello world", "replace": "bye"}


def test_parse_simple_yaml_ignores_lines_without_a_colon():
    text = "id: c1\nnot a valid line\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_handles_colons_inside_the_value():
    text = "find: time: 10:30\n"
    assert parse_simple_yaml(text) == {"find": "time: 10:30"}
