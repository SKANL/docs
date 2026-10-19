# tests/unit/application/test_revision.py
"""Unit coverage for RevisionService (design.md item B, spec:
document-revise -- all 4 requirements / 8 scenarios). Same real-repository-
on-tmp_path style as tests/unit/application/test_status_service.py: the
harness computes diff/scoped-re-validation/provenance; the agent supplies
the replacement text (`new_body`/`new_value`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application.context import ContextService
from docs.application.review import ReviewService
from docs.application.revision import RevisionService
from docs.domain.identity import sha256_content
from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Section, SectionContract, Template, Topic
from docs.domain.normative import NormativeSettings
from docs.domain.sections import apply_stamp, with_frontmatter
from docs.domain.workspace import Workspace
from docs.infrastructure.locking import owned_directory_lock
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_NORMATIVE = NormativeSettings(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)


@pytest.fixture(autouse=True)
def _canonical_workspace_root(canonical_workspace_root: Path) -> None:
    """Opt this module into canonical temporary workspaces."""


class _SpyReviewService:
    """Wraps a real ReviewService and records which sections/document calls
    were made, to prove scoped re-validation touches ONLY the affected
    section(s) + review-document (spec: "Scoped Re-Validation")."""

    def __init__(self, real: ReviewService) -> None:
        self._real = real
        self.section_calls: list[str] = []
        self.document_calls = 0

    def review_section(self, doc_id, template, section_id, strict=False, *, normative):
        self.section_calls.append(section_id)
        return self._real.review_section(doc_id, template, section_id, strict=strict, normative=normative)

    def review_document(self, doc_id, template, strict=False, *, manifest_exists, manifest_size, normative):
        self.document_calls += 1
        return self._real.review_document(
            doc_id, template, strict=strict,
            manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )


def _template() -> Template:
    return Template(
        type="documento-generico",
        title="Doc",
        context_schema=ContextSchema(
            topics=[Topic(id="alumno", title="Alumno", required=True, multiline=True, consumed_by=["introduccion"])]
        ),
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="conclusiones", title="Conclusiones", order=2, required=True),
        ],
        section_contracts={
            "introduccion": SectionContract(),
            "conclusiones": SectionContract(),
        },
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def section_repo(workspace: Workspace) -> JsonSectionRepository:
    return JsonSectionRepository(workspace)


@pytest.fixture
def context_service(workspace: Workspace) -> ContextService:
    context_repo = JsonContextRepository(workspace)
    document_repo = JsonDocumentRepository(workspace)
    workspace.doc_root("alpha").mkdir(parents=True)
    document_repo.write_document(Document(id="alpha", title="Alpha", template="documento-generico"))
    document_repo.register(
        DocumentSummary(id="alpha", title="Alpha", template="documento-generico", created_at="t")
    )
    return ContextService(context_repo, document_repo, ContextMarkdownAdapter())


@pytest.fixture
def spy_review(section_repo: JsonSectionRepository) -> _SpyReviewService:
    return _SpyReviewService(ReviewService(section_repo))


def _lock(directory: Path):
    return owned_directory_lock(directory / ".revision.lock")


@pytest.fixture
def service(section_repo, spy_review, context_service) -> RevisionService:
    return RevisionService(section_repo, spy_review, context_service, JsonEvidenceRepository(), _lock)


def _config(tmp_path: Path) -> dict:
    doc_root = tmp_path / "documents" / "alpha"
    return {"paths": {"sections_dir": str(doc_root / "sections")}}


def _write_section(section_repo: JsonSectionRepository, order: int, section_id: str, body: str) -> None:
    metadata = apply_stamp({}, section_id, section_id.title(), body, "hash", "ai-agent", "gpt", "t0")
    section_repo.write_section("alpha", order, section_id, with_frontmatter(body, metadata))


# ── Requirement: Revise Diff Output ─────────────────────────────────────

def test_revise_returns_before_after_markdown_and_a_change_summary(tmp_path, section_repo, service):
    _write_section(section_repo, 1, "introduccion", "Texto original.")

    result = service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "Texto revisado.", "aclarar alcance",
        normative=_NORMATIVE, now="t1",
    )

    assert result.before == "Texto original."
    assert result.after == "Texto revisado."
    assert result.summary != "" and result.summary != "Sin cambios."


def test_revise_topic_returns_before_after_value_and_a_change_summary(tmp_path, section_repo, service):
    _write_section(section_repo, 1, "introduccion", "Texto original.")

    result = service.revise_topic(
        "alpha", _template(), _config(tmp_path), "alumno", "Nuevo valor de contexto.", "actualizar alumno",
        normative=_NORMATIVE, now="t1",
    )

    assert result.before == ""
    assert "Nuevo valor de contexto." in result.after
    assert result.summary != "Sin cambios."


# ── Requirement: Scoped Re-Validation ───────────────────────────────────

def test_revise_revalidates_only_the_edited_section_plus_document(tmp_path, section_repo, service, spy_review):
    _write_section(section_repo, 1, "introduccion", "Texto original.")
    _write_section(section_repo, 2, "conclusiones", "Cierre.")

    service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "Texto revisado.", "aclarar alcance",
        normative=_NORMATIVE, now="t1",
    )

    assert spy_review.section_calls == ["introduccion"]
    assert spy_review.document_calls == 1


def test_revise_topic_ripples_to_dependent_sections_and_skips_the_rest(tmp_path, section_repo, service, spy_review):
    _write_section(section_repo, 1, "introduccion", "Texto original.")
    _write_section(section_repo, 2, "conclusiones", "Cierre.")

    result = service.revise_topic(
        "alpha", _template(), _config(tmp_path), "alumno", "Nuevo valor.", "actualizar alumno",
        normative=_NORMATIVE, now="t1",
    )

    assert result.changed_sections == ["introduccion"]
    assert spy_review.section_calls == ["introduccion"]
    assert "conclusiones" not in spy_review.section_calls
    assert spy_review.document_calls == 1


# ── Requirement: Change Provenance ──────────────────────────────────────

def test_revise_appends_a_provenance_entry_to_the_revision_log(tmp_path, section_repo, service):
    _write_section(section_repo, 1, "introduccion", "Texto original.")

    result = service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "Texto revisado.", "aclarar alcance",
        normative=_NORMATIVE, now="2026-07-30T10:00:00",
    )

    log_path = Path(_config(tmp_path)["paths"]["sections_dir"]) / "_revisions" / "revision-log.json"
    state = json.loads(log_path.read_text(encoding="utf-8"))
    entry = state["entries"][0]
    assert entry["request"] == "aclarar alcance"
    assert entry["section_id"] == "introduccion"
    assert entry["ts"] == "2026-07-30T10:00:00"
    assert entry["diff_path"] == result.diff_path
    assert Path(entry["diff_path"]).exists()


def test_revise_log_accumulates_entries_in_order_across_calls(tmp_path, section_repo, service):
    _write_section(section_repo, 1, "introduccion", "V1")

    service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "V2", "cambio 1",
        normative=_NORMATIVE, now="t1",
    )
    service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "V3", "cambio 2",
        normative=_NORMATIVE, now="t2",
    )
    service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "V4", "cambio 3",
        normative=_NORMATIVE, now="t3",
    )

    log_path = Path(_config(tmp_path)["paths"]["sections_dir"]) / "_revisions" / "revision-log.json"
    state = json.loads(log_path.read_text(encoding="utf-8"))
    assert [entry["request"] for entry in state["entries"]] == ["cambio 1", "cambio 2", "cambio 3"]


def test_revise_persists_review_issues_and_a_stable_id_in_the_log_entry(tmp_path, section_repo, context_service):
    from docs.domain.review import Issue, ReviewResult

    class _Fake:
        def review_section(self, *a, **k):
            return ReviewResult([Issue("error", "falta evidencia", code="X1", section="introduccion")])

        def review_document(self, *a, **k):
            return ReviewResult([Issue("warning", "global", code="X2")])

    service = RevisionService(section_repo, _Fake(), context_service, JsonEvidenceRepository(), _lock)
    _write_section(section_repo, 1, "introduccion", "V1")
    service.revise(
        "alpha", _template(), _config(tmp_path), "introduccion", "V2", "r",
        normative=_NORMATIVE, now="t1",
    )

    log_path = Path(_config(tmp_path)["paths"]["sections_dir"]) / "_revisions" / "revision-log.json"
    entry = json.loads(log_path.read_text(encoding="utf-8"))["entries"][0]
    assert [i["code"] for i in entry["issues"]] == ["X1", "X2"]
    assert entry["issues"][0]["section"] == "introduccion"
    body = {k: v for k, v in entry.items() if k != "id"}
    assert entry["id"] == sha256_content(body)


def test_revise_topic_persists_issues_too(tmp_path, section_repo, context_service):
    from docs.domain.review import Issue, ReviewResult

    class _Fake:
        def review_section(self, *a, **k):
            return ReviewResult([Issue("error", "m", code="S1")])

        def review_document(self, *a, **k):
            return ReviewResult()

    service = RevisionService(section_repo, _Fake(), context_service, JsonEvidenceRepository(), _lock)
    _write_section(section_repo, 1, "introduccion", "V1")
    service.revise_topic(
        "alpha", _template(), _config(tmp_path), "alumno", "Ana", "r", normative=_NORMATIVE, now="t1",
    )
    log_path = Path(_config(tmp_path)["paths"]["sections_dir"]) / "_revisions" / "revision-log.json"
    entry = json.loads(log_path.read_text(encoding="utf-8"))["entries"][0]
    assert [i["code"] for i in entry["issues"]] == ["S1"]
    assert entry["id"]


# ── Requirement: Revise Scope Boundary ──────────────────────────────────

def test_revise_rejects_an_unknown_section_id_as_structurally_out_of_scope(tmp_path, service):
    with pytest.raises(ValueError, match="revise"):
        service.revise(
            "alpha", _template(), _config(tmp_path), "seccion-inexistente", "texto", "agregar sección",
            normative=_NORMATIVE, now="t1",
        )


def test_revise_topic_rejects_an_unknown_topic_id_as_structurally_out_of_scope(tmp_path, service):
    with pytest.raises(ValueError, match="revise"):
        service.revise_topic(
            "alpha", _template(), _config(tmp_path), "tema-inexistente", "valor", "agregar tema",
            normative=_NORMATIVE, now="t1",
        )


def test_resolve_target_classifies_section_and_topic_ids(tmp_path, service):
    template = _template()
    assert service.resolve_target(template, "introduccion") == "section"
    assert service.resolve_target(template, "alumno") == "topic"
    with pytest.raises(ValueError, match="revise"):
        service.resolve_target(template, "no-existe")


# ── Hardening H8: provenance is atomic and collision-safe ───────────────

def test_concurrent_revisions_neither_lose_log_entries_nor_overwrite_a_diff(
    tmp_path, section_repo, spy_review, context_service
):
    from concurrent.futures import ThreadPoolExecutor

    service = RevisionService(
        section_repo, spy_review, context_service, JsonEvidenceRepository(),
        provenance_lock=_lock,
    )
    config = _config(tmp_path)

    # The provenance step is the unit under test; section writes race on their own file.
    def record(i: int) -> str:
        return service._record(
            config, "001-introduccion", f"diff {i}", request=f"cambio {i}", target_id="introduccion",
            before_hash="a", after_hash="b", ripple=[], ts=f"t{i}", issues=[],
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        diff_paths = list(pool.map(record, range(8)))

    revisions = Path(config["paths"]["sections_dir"]) / "_revisions"
    state = json.loads((revisions / "revision-log.json").read_text(encoding="utf-8"))
    assert len(state["entries"]) == 8
    assert len(set(diff_paths)) == 8
    assert len(list(revisions.glob("*.diff"))) == 8


def test_interrupted_log_write_keeps_the_previous_log_intact(tmp_path, section_repo, service, monkeypatch):
    _write_section(section_repo, 1, "introduccion", "V1")
    config = _config(tmp_path)
    service.revise("alpha", _template(), config, "introduccion", "V2", "uno", normative=_NORMATIVE, now="t1")
    log_path = Path(config["paths"]["sections_dir"]) / "_revisions" / "revision-log.json"
    before = log_path.read_text(encoding="utf-8")

    real_write = section_repo.write_raw_text
    calls = []

    def interrupted(path, text):
        calls.append(path)
        if len(calls) == 2:  # the diff (1st write) succeeds; only the log (2nd) is interrupted
            raise OSError("disk went away")
        real_write(path, text)

    monkeypatch.setattr(section_repo, "write_raw_text", interrupted)
    with pytest.raises(OSError):
        service.revise("alpha", _template(), config, "introduccion", "V3", "dos", normative=_NORMATIVE, now="t2")

    assert len(calls) == 2 and calls[1] == log_path
    assert log_path.read_text(encoding="utf-8") == before


def test_diff_numbering_never_reuses_a_number_after_a_diff_is_removed(tmp_path, service):
    config = _config(tmp_path)

    def record(i: int) -> str:
        return service._record(
            config, "001-introduccion", f"diff {i}", request=f"cambio {i}", target_id="introduccion",
            before_hash="a", after_hash="b", ripple=[], ts=f"t{i}", issues=[],
        )

    first, second, third = record(1), record(2), record(3)
    Path(first).unlink()  # a gap below the max: glob-count numbering would now reuse "3"
    fourth = record(4)

    assert len({first, second, third, fourth}) == 4
    assert Path(third).read_text(encoding="utf-8") == "diff 3"
    assert Path(fourth).read_text(encoding="utf-8") == "diff 4"


def test_revision_service_requires_a_provenance_lock(section_repo, spy_review, context_service):
    with pytest.raises(TypeError):
        RevisionService(section_repo, spy_review, context_service, JsonEvidenceRepository())  # type: ignore[call-arg]
