from docs.domain.models.template import Field, Topic
from docs.domain.context import is_prose_topic, missing_fields, TopicStatus


def _prose_topic(required: bool = True) -> Topic:
    return Topic(id="intro", title="Introducción", required=required, multiline=True)


def _field_topic(required: bool = True, field_required: bool | None = None) -> Topic:
    field_kwargs = {} if field_required is None else {"required": field_required}
    return Topic(
        id="alumno",
        title="Alumno",
        required=required,
        fields=[Field(key="nombre", label="Nombre", **field_kwargs)],
    )


def test_is_prose_topic_true_when_multiline():
    assert is_prose_topic(_prose_topic()) is True


def test_is_prose_topic_true_when_no_fields():
    topic = Topic(id="x", title="X", multiline=False, fields=[])
    assert is_prose_topic(topic) is True


def test_is_prose_topic_false_when_fields_and_not_multiline():
    assert is_prose_topic(_field_topic()) is False


def test_prose_required_and_empty_is_missing():
    assert missing_fields(_prose_topic(required=True), None) == ["(texto)"]


def test_prose_required_and_blank_is_missing():
    assert missing_fields(_prose_topic(required=True), "   ") == ["(texto)"]


def test_prose_not_required_and_empty_is_not_missing():
    assert missing_fields(_prose_topic(required=False), None) == []


def test_prose_with_text_is_not_missing():
    assert missing_fields(_prose_topic(required=True), "Ya hay contenido.") == []


def test_field_missing_when_required_and_absent_answer():
    topic = _field_topic(required=True)
    assert missing_fields(topic, None) == ["Nombre"]
    assert missing_fields(topic, {}) == ["Nombre"]


def test_field_missing_when_whitespace_only_value():
    topic = _field_topic(required=True)
    assert missing_fields(topic, {"nombre": "   "}) == ["Nombre"]


def test_field_not_missing_when_value_present():
    topic = _field_topic(required=True)
    assert missing_fields(topic, {"nombre": "Ana"}) == []


def test_field_level_required_overrides_topic_level_true_to_false():
    # topic.required=True but field.required=False -> field is NOT forced missing
    topic = _field_topic(required=True, field_required=False)
    assert missing_fields(topic, None) == []


def test_field_level_required_overrides_topic_level_false_to_true():
    # topic.required=False but field.required=True -> field IS forced missing
    topic = _field_topic(required=False, field_required=True)
    assert missing_fields(topic, None) == ["Nombre"]


def test_field_falls_back_to_topic_required_when_unset():
    # field.required unset (default False on the model) still falls back to
    # topic.required via missing_fields' explicit fallback, not the model default.
    topic = _field_topic(required=True, field_required=None)
    assert missing_fields(topic, None) == ["Nombre"]


def test_sensitive_does_not_affect_completion():
    topic = Topic(
        id="alumno", title="Alumno", required=True,
        fields=[Field(key="dni", label="DNI", required=True, sensitive=True)],
    )
    assert missing_fields(topic, {"dni": "12345678"}) == []
    assert missing_fields(topic, None) == ["DNI"]


def test_topic_status_complete_is_derived_from_missing():
    status = TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[])
    assert status.complete is True
    status2 = TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Nombre"])
    assert status2.complete is False


def test_topic_status_to_dict():
    status = TopicStatus(id="alumno", title="Alumno", required=True, exists=False, missing=["Nombre"])
    assert status.to_dict() == {
        "id": "alumno", "title": "Alumno", "required": True,
        "exists": False, "missing": ["Nombre"], "complete": False,
    }
