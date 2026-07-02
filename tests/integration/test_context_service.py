from pathlib import Path

import pytest

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Field, Template, Topic
from docs.domain.ports.document_repository import DocumentNotFoundError
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.application.context import ContextService


def _template() -> Template:
    return Template(
        type="documento-generico",
        title="Doc",
        context_schema=ContextSchema(
            topics=[
                Topic(
                    id="alumno",
                    title="Alumno",
                    required=True,
                    fields=[
                        Field(key="nombre", label="Nombre", required=True),
                        Field(key="legajo", label="Legajo", required=False),
                    ],
                ),
                Topic(id="intro", title="Introducción", required=True, multiline=True),
            ]
        ),
    )


@pytest.fixture
def setup(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    document_repo = JsonDocumentRepository(ws)
    context_repo = JsonContextRepository(ws)
    # Build the doc workspace manually: Slice 1's create() needs a template file on
    # disk, but this integration test only needs doc_root("alpha") to exist plus a
    # registered document so document_repo.exists("alpha") is True.
    ws.doc_root("alpha").mkdir(parents=True)
    document_repo.write_document(Document(id="alpha", title="Alpha", template="documento-generico"))
    document_repo.register(
        DocumentSummary(id="alpha", title="Alpha", template="documento-generico", created_at="t")
    )
    service = ContextService(context_repo, document_repo)
    return service, _template()


def test_status_reports_missing_for_unanswered_required_topics(setup):
    service, template = setup
    statuses = service.status("alpha", template)
    assert [s.id for s in statuses] == ["alumno", "intro"]
    assert statuses[0].missing == ["Nombre"]
    assert statuses[1].missing == ["(texto)"]


def test_set_field_topic_merges_single_field(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    statuses = service.status("alpha", template)
    assert statuses[0].missing == []


def test_set_unknown_topic_raises(setup):
    service, template = setup
    with pytest.raises(ValueError):
        service.set("alpha", template, "ghost", "x", field="nombre")


def test_set_unknown_field_raises(setup):
    service, template = setup
    with pytest.raises(ValueError):
        service.set("alpha", template, "alumno", "x", field="ghost")


def test_set_prose_topic_ignores_field_arg(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.", field="ignored")
    statuses = service.status("alpha", template)
    assert statuses[1].missing == []


def test_set_regenerates_index(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    index_path = service.context_repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert index_path.exists()


def test_show_returns_raw_text(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    assert "Texto." in service.show("alpha", "intro")


def test_show_missing_topic_raises_file_not_found(setup):
    service, template = setup
    with pytest.raises(FileNotFoundError):
        service.show("alpha", "intro")


def test_show_does_not_validate_against_schema(setup):
    # legacy quirk: show works for a topic id that doesn't exist in the schema,
    # as long as the file happens to exist on disk.
    service, template = setup
    service.context_repo.write_topic("alpha", template.context_schema.topics[1], "manual write")
    assert service.show("alpha", "intro") != ""


def test_remove_deletes_topic_and_no_error_if_absent(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    service.remove("alpha", template, "intro")
    with pytest.raises(FileNotFoundError):
        service.show("alpha", "intro")
    service.remove("alpha", template, "intro")  # second call: no error


def test_status_and_set_raise_for_unknown_document(setup):
    service, template = setup
    with pytest.raises(DocumentNotFoundError):
        service.status("ghost", template)
    with pytest.raises(DocumentNotFoundError):
        service.set("ghost", template, "intro", "x")


def test_ingest_writes_known_topics_and_regenerates_index(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    requests_text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): Ana\n"
        "- **Legajo** (`legajo`): 123\n"
        "\n"
        "## Introducción (`intro`) [prosa]\n"
        "\n"
        "<<<\n"
        "Texto nuevo.\n"
        ">>>\n"
    )
    service.context_repo.write_requests("alpha", requests_text)

    written = service.ingest("alpha", template)

    assert set(written) == {"alumno", "intro"}
    statuses = service.status("alpha", template)
    assert statuses[0].missing == []
    assert statuses[1].missing == []
    index_path = service.context_repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert index_path.exists()


def test_ingest_merge_never_erases_existing_value(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    service.set("alpha", template, "alumno", "123", field="legajo")
    requests_text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): \n"  # empty answer must NOT erase "Ana"
        "- **Legajo** (`legajo`): \n"
        "\n"
    )
    service.context_repo.write_requests("alpha", requests_text)

    service.ingest("alpha", template)

    value = service.context_repo.read_topic("alpha", template.context_schema.topics[0])
    assert value == {"nombre": "Ana", "legajo": "123"}


def test_ingest_skips_unknown_topic(setup):
    service, template = setup
    service.context_repo.write_requests("alpha", "## Desconocido (`ghost`)\n- **X** (`x`): y\n")
    written = service.ingest("alpha", template)
    assert written == []


def test_ingest_raises_if_requests_file_absent(setup):
    service, template = setup
    with pytest.raises(FileNotFoundError):
        service.ingest("alpha", template)


def test_write_requests_file_renders_pending_questionnaire(setup):
    service, template = setup
    path = service.write_requests_file("alpha", template)
    text = path.read_text(encoding="utf-8")
    assert "`alumno`" in text
    assert "`intro`" in text
    assert path == service.context_repo.workspace.doc_root("alpha") / "context" / "_requests.md"


def test_write_requests_file_only_topic_filters_to_single_topic(setup):
    service, template = setup
    path = service.write_requests_file("alpha", template, only_topic="alumno")
    text = path.read_text(encoding="utf-8")
    assert "`alumno`" in text
    assert "`intro`" not in text
