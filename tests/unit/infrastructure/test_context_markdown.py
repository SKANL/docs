import re

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema, Field, Topic
from docs.infrastructure.persistence.context_markdown import (
    parse_requests,
    parse_topic,
    render_requests,
    render_topic,
)


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


def _requests_schema() -> ContextSchema:
    return ContextSchema(
        topics=[
            Topic(id="alumno", title="Alumno", required=True, fields=[Field(key="nombre", label="Nombre"), Field(key="legajo", label="Legajo")]),
            Topic(id="intro", title="Introducción", required=True, multiline=True, prompt="Contanos el contexto."),
        ]
    )


def test_render_requests_emits_only_pending_topics():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses)
    assert "## Alumno (`alumno`)" in text
    assert "- **Nombre** (`nombre`): Ana" in text
    assert "- **Legajo** (`legajo`): " in text
    assert "## Introducción (`intro`) [prosa]" in text
    assert "> Contanos el contexto." in text
    assert "<<<" in text and ">>>" in text


def test_render_requests_skips_complete_topics():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[]), {"nombre": "Ana", "legajo": "1"}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses)
    assert "alumno" not in text
    assert "intro" in text


def test_render_requests_respects_only_topic():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses, only_topic="intro")
    assert "alumno" not in text
    assert "intro" in text


def test_render_requests_nothing_pending():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[]), {"nombre": "Ana", "legajo": "1"}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=True, missing=[]), "Ya escrito."),
    ]
    text = render_requests(schema, statuses)
    assert text == "_No hay campos pendientes._"


def test_parse_requests_field_and_prose_blocks():
    schema = _requests_schema()
    text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): Ana\n"
        "- **Legajo** (`legajo`): 123\n"
        "\n"
        "## Introducción (`intro`) [prosa]\n"
        "> Contanos el contexto.\n"
        "\n"
        "<<<\n"
        "Texto de respuesta.\n"
        ">>>\n"
    )
    parsed = parse_requests(schema, text)
    assert parsed == {
        "alumno": {"nombre": "Ana", "legajo": "123"},
        "intro": "Texto de respuesta.",
    }


def test_parse_requests_ignores_unknown_topic():
    schema = _requests_schema()
    text = "## Desconocido (`ghost`)\n- **X** (`x`): y\n"
    parsed = parse_requests(schema, text)
    assert parsed == {}


def test_parse_requests_mode_by_delimiter_not_tag():
    schema = _requests_schema()

    # No [prosa] tag, but has <<</>>> delimiter -> must still parse as prose string.
    text_delimiter_without_tag = (
        "## Introducción (`intro`)\n"
        "\n"
        "<<<\n"
        "Texto de respuesta.\n"
        ">>>\n"
    )
    parsed = parse_requests(schema, text_delimiter_without_tag)
    assert parsed == {"intro": "Texto de respuesta."}

    # Has [prosa] tag, but no <<</>>> delimiter (field-style lines instead) ->
    # must still parse as a field dict.
    text_tag_without_delimiter = (
        "## Introducción (`intro`) [prosa]\n"
        "- **Nombre** (`nombre`): Ana\n"
    )
    parsed = parse_requests(schema, text_tag_without_delimiter)
    assert parsed == {"intro": {"nombre": "Ana"}}


def test_render_requests_prose_block_always_blank_even_with_prior_value():
    schema = _requests_schema()
    statuses = [
        (
            TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]),
            "some stale prior text",
        ),
    ]
    text = render_requests(schema, statuses)
    assert "some stale prior text" not in text

    delim_match = re.search(r"<<<\s*\n(.*?)\n\s*>>>", text, re.DOTALL)
    assert delim_match is not None
    assert delim_match.group(1).strip() == ""


def test_render_then_parse_requests_round_trip():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    rendered = render_requests(schema, statuses)
    parsed = parse_requests(schema, rendered)
    assert parsed["alumno"]["nombre"] == "Ana"
    assert parsed["intro"] == ""
