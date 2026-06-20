from pathlib import Path

import pytest

from docs.domain.models.template import Field, Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository


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
