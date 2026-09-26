import json
from pathlib import Path

import pytest

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema, Field, Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository

CURRENT_UNVERSIONED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "workspaces"
    / "legacy"
    / "current-unversioned"
)


@pytest.fixture
def repo(tmp_path: Path) -> JsonContextRepository:
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    (ws.doc_root("alpha")).mkdir(parents=True)
    return JsonContextRepository(ws)


def _prose_topic() -> Topic:
    return Topic(id="intro", title="Introducción", multiline=True)


def _field_topic() -> Topic:
    return Topic(id="alumno", title="Alumno", fields=[Field(key="nombre", label="Nombre")])


def test_write_then_read_prose_topic_roundtrip(repo):
    repo.write_topic("alpha", _prose_topic(), "Hola mundo.")
    assert repo.read_topic("alpha", _prose_topic()) == "Hola mundo."


def test_write_then_read_field_topic_roundtrip(repo):
    repo.write_topic("alpha", _field_topic(), {"nombre": "Ana"})
    assert repo.read_topic("alpha", _field_topic()) == {"nombre": "Ana"}


def test_read_missing_topic_returns_empty(repo):
    assert repo.read_topic("alpha", _prose_topic()) == ""
    assert repo.read_topic("alpha", _field_topic()) == {"nombre": ""}


def test_write_topic_returns_path(repo):
    path = repo.write_topic("alpha", _prose_topic(), "x")
    assert path == repo.workspace.doc_root("alpha") / "context" / "intro.md"
    assert path.exists()


def test_topic_exists_true_and_false(repo):
    assert repo.topic_exists("alpha", "intro") is False
    repo.write_topic("alpha", _prose_topic(), "x")
    assert repo.topic_exists("alpha", "intro") is True


def test_remove_topic_deletes_file(repo):
    repo.write_topic("alpha", _prose_topic(), "x")
    repo.remove_topic("alpha", "intro")
    assert repo.topic_exists("alpha", "intro") is False


def test_remove_topic_no_error_if_absent(repo):
    repo.remove_topic("alpha", "ghost")  # must not raise


def test_read_topic_raw_returns_text(repo):
    repo.write_topic("alpha", _prose_topic(), "Hola mundo.")
    assert repo.read_topic_raw("alpha", "intro") == "# Introducción\n\nHola mundo.\n"


def test_read_topic_raw_missing_raises(repo):
    with pytest.raises(FileNotFoundError):
        repo.read_topic_raw("alpha", "ghost")


def _schema() -> ContextSchema:
    return ContextSchema(
        topics=[
            Topic(id="alumno", title="Alumno", consumed_by=["introduccion"], fields=[Field(key="nombre", label="Nombre")]),
            Topic(id="intro", title="Introducción", multiline=True, consumed_by=["introduccion", "resumen"]),
        ]
    )


def _statuses() -> list[TopicStatus]:
    return [
        TopicStatus(id="alumno", title="Alumno", required=False, exists=True, missing=["Nombre"]),
        TopicStatus(id="intro", title="Introducción", required=False, exists=False, missing=[]),
    ]


def test_regenerate_index_writes_json_and_md(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    assert path == repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert path.exists()
    assert (path.parent / "index.md").exists()


def test_index_json_schema_key_and_sort_keys(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["schema"] == 1
    # sort_keys=True -> top-level keys alphabetical: by_section, schema, topics
    assert text.index('"by_section"') < text.index('"schema"') < text.index('"topics"')


def test_index_json_topic_order_matches_schema_order(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [t["id"] for t in data["topics"]] == ["alumno", "intro"]
    assert data["topics"][0]["complete"] is False
    assert data["by_section"]["introduccion"] == ["alumno", "intro"]
    assert data["by_section"]["resumen"] == ["intro"]


def test_index_md_contains_human_table(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    text = (path.parent / "index.md").read_text(encoding="utf-8")
    assert "| Tema | Archivo | Completo | Consumido por |" in text
    assert "| Alumno | alumno.md | no | introduccion |" in text
    assert "| Introducción | intro.md | sí | introduccion, resumen |" in text


def test_current_unversioned_fixture_preserves_prose_structured_values_and_projection() -> None:
    fixture_repo = JsonContextRepository(
        Workspace(
            documents_dir=CURRENT_UNVERSIONED / "documents",
            templates_dir=CURRENT_UNVERSIONED / "templates",
        )
    )
    purpose = Topic(id="purpose", title="Purpose", multiline=True)
    owner = Topic(id="owner", title="Owner", fields=[Field(key="name", label="Name")])

    assert fixture_repo.read_topic("sanitized-report", purpose) == (
        "Characterize the current unversioned workspace without personal data."
    )
    assert fixture_repo.read_topic("sanitized-report", owner) == {"name": "Example Author"}
    index_path = (
        CURRENT_UNVERSIONED
        / "documents"
        / "sanitized-report"
        / "context"
        / "index.json"
    )
    assert json.loads(index_path.read_text(encoding="utf-8"))["schema"] == 1
    assert fixture_repo.read_requests("sanitized-report") == "_No pending requests._\n"
