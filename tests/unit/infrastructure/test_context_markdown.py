from docs.domain.models.template import Field, Topic
from docs.infrastructure.persistence.context_markdown import render_topic, parse_topic


def _prose_topic() -> Topic:
    return Topic(id="intro", title="Introducción", multiline=True)


def _field_topic() -> Topic:
    return Topic(
        id="alumno",
        title="Alumno",
        fields=[
            Field(key="nombre", label="Nombre"),
            Field(key="legajo", label="Legajo"),
        ],
    )


def test_render_prose_topic_exact_format():
    text = render_topic(_prose_topic(), "Hola mundo.")
    assert text == "# Introducción\n\nHola mundo.\n"


def test_render_prose_topic_with_none_values_is_empty_body():
    text = render_topic(_prose_topic(), None)
    assert text == "# Introducción\n\n\n"


def test_render_field_topic_exact_format():
    text = render_topic(_field_topic(), {"nombre": "Ana", "legajo": "123"})
    expected = (
        "**Alumno**\n"
        "\n"
        "| Campo | Información |\n"
        "| :---- | :---- |\n"
        "| **Nombre** | Ana |\n"
        "| **Legajo** | 123 |\n"
    )
    assert text == expected


def test_render_field_topic_missing_values_are_blank_cells():
    text = render_topic(_field_topic(), {"nombre": "Ana"})
    assert "| **Legajo** |  |" in text


def test_parse_prose_topic_strips_heading_and_whitespace():
    text = "# Introducción\n\n  Hola mundo.  \n"
    assert parse_topic(_prose_topic(), text) == "Hola mundo."


def test_parse_field_topic_extracts_each_field():
    text = (
        "**Alumno**\n\n"
        "| Campo | Información |\n"
        "| :---- | :---- |\n"
        "| **Nombre** | Ana |\n"
        "| **Legajo** | 123 |\n"
    )
    assert parse_topic(_field_topic(), text) == {"nombre": "Ana", "legajo": "123"}


def test_parse_field_topic_cleans_markdown_noise():
    text = (
        "| **Nombre** | **Ana** *Garcia* `code` |\n"
        "| **Legajo** | 123 |\n"
    )
    parsed = parse_topic(_field_topic(), text)
    assert parsed["nombre"] == "Ana Garcia code"


def test_parse_field_topic_missing_row_is_empty_string():
    text = "| **Nombre** | Ana |\n"
    parsed = parse_topic(_field_topic(), text)
    assert parsed == {"nombre": "Ana", "legajo": ""}


def test_round_trip_prose():
    original = "Texto con\nvarias líneas."
    rendered = render_topic(_prose_topic(), original)
    assert parse_topic(_prose_topic(), rendered) == original


def test_round_trip_field_topic():
    values = {"nombre": "Ana", "legajo": "123"}
    rendered = render_topic(_field_topic(), values)
    assert parse_topic(_field_topic(), rendered) == values
