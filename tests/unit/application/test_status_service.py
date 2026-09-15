# tests/unit/application/test_status_service.py
"""Unit coverage for StatusService (design.md item I, `doc status`):
aggregate-and-read summary over context/sections/ingest/figures/output --
introduces no new state (ADR-I). Same real-repository-on-tmp_path style as
tests/integration/test_context_pack_service.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application.context import ContextService
from docs.application.provenance import ProvenanceLedger
from docs.application.review import ReviewService
from docs.application.status import StatusService
from docs.application.status_reader import StatusReader, StatusSnapshot
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest
from docs.domain.document_status import DocumentStatus
from docs.domain.identity import sha256_content, sha256_file
from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Section, SectionContract, Template, Topic
from docs.domain.normative import NormativeSettings
from docs.domain.sections import apply_stamp, with_frontmatter
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_NORMATIVE = NormativeSettings(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)


class _StatusReaderStub:
    def __init__(self, status: StatusSnapshot) -> None:
        self.status = status
        self.document_roots: list[Path] = []

    def read(self, document_root: Path) -> StatusSnapshot:
        self.document_roots.append(document_root)
        return self.status


def _template() -> Template:
    return Template(
        type="documento-generico",
        title="Doc",
        context_schema=ContextSchema(topics=[Topic(id="alumno", title="Alumno", required=True, multiline=True)]),
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="conclusiones", title="Conclusiones", order=2, required=True),
        ],
        section_contracts={
            "introduccion": SectionContract(required_content=["alcance"]),
            "conclusiones": SectionContract(),
        },
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def document_repo(workspace: Workspace) -> JsonDocumentRepository:
    repo = JsonDocumentRepository(workspace)
    workspace.doc_root("alpha").mkdir(parents=True)
    repo.write_document(Document(id="alpha", title="Alpha", template="documento-generico"))
    repo.register(DocumentSummary(id="alpha", title="Alpha", template="documento-generico", created_at="t"))
    return repo


@pytest.fixture
def service(workspace: Workspace, document_repo: JsonDocumentRepository) -> StatusService:
    section_repo = JsonSectionRepository(workspace)
    context_repo = JsonContextRepository(workspace)
    context_service = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
    review_service = ReviewService(section_repo)
    return StatusService(section_repo, context_service, review_service, document_repo)


def _config(tmp_path: Path) -> dict:
    doc_root = tmp_path / "documents" / "alpha"
    return {
        "paths": {
            "inbox_dir": str(doc_root / "inbox"),
            "sections_dir": str(doc_root / "sections"),
            "output_draft_dir": str(doc_root / "output" / "draft"),
            "output_final_dir": str(doc_root / "output" / "final"),
            "runs_dir": str(doc_root / "runs"),
        },
    }


def test_status_summary_reports_fresh_document(tmp_path, service):
    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert (status.context_filled, status.context_total) == (0, 1)
    assert status.context_missing_topics == ["alumno"]
    assert (status.sections_authored, status.sections_total) == (0, 2)
    assert status.sections_missing == ["introduccion", "conclusiones"]
    assert status.sections_scaffold == []
    assert status.sections_needs_review == []
    assert status.ingest_ran is False
    assert status.classification_pending == 0
    assert status.figures_count == 0
    assert status.output_draft_exists is False
    assert status.output_final_exists is False
    assert status.lifecycle == "draft"
    assert status.build_version is None
    assert "v2" not in status.to_dict()


def test_status_summary_reports_partially_completed_document(tmp_path, workspace, service):
    doc_root = workspace.doc_root("alpha")
    section_repo = JsonSectionRepository(workspace)

    # Context filled.
    service.context_service.set("alpha", _template(), "alumno", "Texto introductorio.")

    # `introduccion`: scaffold section, still contains PENDIENTE + harness-scaffold stamp.
    scaffold_metadata = {"managed_by": "docs-harness", "authored_by": "harness-scaffold", "schema": 3}
    section_repo.write_section(
        "alpha", 1, "introduccion",
        with_frontmatter("PENDIENTE: documentar alcance con evidencia del ledger, contexto o fuentes.", scaffold_metadata),
    )

    # `conclusiones`: authored (real content, no PENDIENTE, non-scaffold authored_by), no gaps.
    conclusiones_body = "# Conclusiones\n\nCierre del trabajo."
    authored_metadata = apply_stamp({}, "conclusiones", "Conclusiones", conclusiones_body, "hash", "ai-agent", "gpt", "t")
    section_repo.write_section("alpha", 2, "conclusiones", with_frontmatter(conclusiones_body, authored_metadata))

    # Ingest artifacts.
    inbox_dir = doc_root / "inbox"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "_detection.json").write_text("{}", encoding="utf-8")
    (inbox_dir / "_classification-queue.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "entries": {
                    "a.pdf": {"proposed_role": "manual", "confidence": "high", "signals": [], "confirmed_role": None},
                    "b.pdf": {"proposed_role": "manual", "confidence": "high", "signals": [], "confirmed_role": "manual"},
                },
            }
        ),
        encoding="utf-8",
    )

    # Figure catalog.
    sections_dir = doc_root / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    (sections_dir / "figure-catalog.json").write_text(
        json.dumps({"figures": [{"id": "fig-aaaaaaaa"}, {"id": "fig-bbbbbbbb"}]}), encoding="utf-8"
    )

    # Output draft artifact.
    output_draft_dir = doc_root / "output" / "draft"
    output_draft_dir.mkdir(parents=True)
    (output_draft_dir / "alpha-draft.docx").write_text("x", encoding="utf-8")

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert (status.context_filled, status.context_total) == (1, 1)
    assert status.context_missing_topics == []
    assert (status.sections_authored, status.sections_total) == (2, 2)
    assert status.sections_missing == []
    assert status.sections_scaffold == ["introduccion"]
    # `introduccion` has a missing required_content gap AND is scaffold -> flagged.
    assert status.sections_needs_review == ["introduccion"]
    assert status.ingest_ran is True
    assert status.classification_pending == 1
    assert status.figures_count == 2
    assert status.output_draft_exists is True
    assert status.output_final_exists is False


# --- Phase 6: lifecycle + build version (item F, spec: document-lifecycle) -


def test_status_summary_reports_authored_section_without_stamp_as_not_scaffold(tmp_path, workspace, service):
    """Regression: authoring a section (removing PENDIENTE) without running
    `stamp-section` leaves `authored_by` at its default 'harness-scaffold'
    value forever, and a `body_hash` written once at scaffold time is never
    refreshed either. Status must classify by body content, not by an
    unstamped provenance field or a hash nobody kept current -- otherwise a
    fully-authored, review-passed document shows every section as scaffold
    forever."""
    section_repo = JsonSectionRepository(workspace)
    service.context_service.set("alpha", _template(), "alumno", "Texto introductorio.")

    authored_body = "# Introducción\n\nAlcance definido y evidenciado.\n"
    metadata = {
        "managed_by": "docs-harness",
        "authored_by": "harness-scaffold",  # never stamped
        "schema": 3,
        "section_id": "introduccion",
        "title": "Introducción",
        "body_hash": "stale-hash-from-original-scaffold",  # never refreshed
    }
    section_repo.write_section("alpha", 1, "introduccion", with_frontmatter(authored_body, metadata))

    conclusiones_body = "# Conclusiones\n\nCierre del trabajo.\n"
    section_repo.write_section(
        "alpha", 2, "conclusiones",
        with_frontmatter(
            conclusiones_body,
            {"managed_by": "docs-harness", "authored_by": "harness-scaffold", "schema": 3},
        ),
    )

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert status.sections_scaffold == []


def test_status_summary_reports_final_lifecycle_after_mark_final(tmp_path, document_repo, service):
    document = document_repo.read_document("alpha")
    document_repo.write_document(document.model_copy(update={"lifecycle": "final"}))

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert status.lifecycle == "final"


def test_status_summary_reports_latest_build_version_from_runs_dir(tmp_path, service):
    runs_dir = tmp_path / "documents" / "alpha" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "1-pipeline-assemble.json").write_text(json.dumps({"build_version": 1}), encoding="utf-8")
    (runs_dir / "2-pipeline-assemble.json").write_text(json.dumps({"build_version": 2}), encoding="utf-8")

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert status.build_version == 2


def test_status_summary_exposes_generated_cover_variant_and_missing_slots(tmp_path, service):
    config = _config(tmp_path)
    config.update(
        {
            "title": "Cover report",
            "cover": {
                "mode": "generated",
                "variant": "academic",
                "slots": {"title": "{{title}}", "author": "{{project.author}}"},
            },
        }
    )

    status = service.status_summary("alpha", _template(), config, normative=_NORMATIVE)

    assert status.to_dict()["cover"] == {
        "mode": "generated",
        "variant": "academic",
        "missing_slots": ["author"],
    }


def test_document_status_serializes_optional_v2_observability() -> None:
    status = DocumentStatus(
        doc_id="alpha",
        context_filled=0,
        context_total=0,
        v2_capabilities={"pandoc": {"available": True}},
        v2_execution={"results": []},
        v2_provenance={"run_id": "run-1"},
        v2_succeeded=True,
        unsupported_stages=["accessibility-review"],
        publication_blockers=["publish disallowed by pipeline policy"],
    )

    assert status.to_dict()["v2"] == {
        "capabilities": {"pandoc": {"available": True}},
        "execution": {"results": []},
        "provenance": {"run_id": "run-1"},
        "succeeded": True,
        "unsupported_stages": ["accessibility-review"],
        "publication_blockers": ["publish disallowed by pipeline policy"],
    }


def test_status_summary_reads_v2_observability_through_reader(tmp_path, service, workspace):
    reader = _StatusReaderStub(
        StatusSnapshot(
            execution={"schema": "docs.build/v2"},
            provenance={"run_id": "run-1"},
            succeeded=True,
            unsupported_stages=["accessibility-review"],
            publication_blockers=["required capability unavailable: soffice"],
        )
    )
    service.status_reader_reader = reader

    status = service.status_summary("alpha", _template(), _config(tmp_path), normative=_NORMATIVE)

    assert reader.document_roots == [workspace.doc_root("alpha")]
    assert status.v2_succeeded is True
    assert status.v2_execution == {"schema": "docs.build/v2"}
    assert status.v2_provenance == {"run_id": "run-1"}
    assert status.unsupported_stages == ["accessibility-review"]
    assert status.publication_blockers == ["required capability unavailable: soffice"]


def test_status_reader_reader_loads_manifest_and_matching_provenance_from_document_root(tmp_path: Path) -> None:
    doc_root = tmp_path / "alpha"
    artifact = doc_root / "output" / "v2" / "alpha.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("artifact", encoding="utf-8")
    manifest = BuildManifest(
        document_id="alpha",
        artifacts=(ArtifactRef(str(artifact), "a" * 64, ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-001",
    )
    artifact.with_suffix(".docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    source = doc_root / "source.md"
    source.write_text("source", encoding="utf-8")
    provenance = ProvenanceLedger(doc_root / "runs" / "v2-provenance.json")
    expected_provenance = provenance.record_run("build-001", inputs=(source,), outputs=(artifact,))

    snapshot = StatusReader().read(doc_root)

    assert snapshot.manifest == manifest
    assert snapshot.provenance == expected_provenance


def test_status_reader_reader_derives_unsupported_stages_and_publication_blockers_from_runtime_results(
    tmp_path: Path,
) -> None:
    doc_root = tmp_path / "alpha"
    artifact = doc_root / "output" / "v2" / "alpha.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("artifact", encoding="utf-8")
    manifest = BuildManifest(
        document_id="alpha",
        artifacts=(ArtifactRef(str(artifact), "a" * 64, ArtifactState.READY),),
        verification={"passed": False},
    )
    payload = manifest.to_dict()
    payload["report"] = {
        "execution": {
            "results": [
                {"stage": "accessibility-review", "outcome": "unsupported", "errors": []},
                {"stage": "publish-draft", "outcome": "failed", "errors": ["publish disallowed by pipeline policy"]},
                {"stage": "package-release", "outcome": "failed", "errors": ["release packaging failed"]},
            ]
        }
    }
    artifact.with_suffix(".docx.manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    snapshot = StatusReader().read(doc_root)

    assert snapshot.unsupported_stages == ["accessibility-review"]
    assert snapshot.publication_blockers == [
        "publish disallowed by pipeline policy",
        "release packaging failed",
    ]


def test_status_reader_reader_fails_open_for_invalid_manifest(tmp_path: Path) -> None:
    doc_root = tmp_path / "alpha"
    manifest_path = doc_root / "output" / "v2" / "alpha.docx.manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not-json", encoding="utf-8")

    snapshot = StatusReader().read(doc_root)

    assert snapshot.manifest is None
    assert snapshot.provenance is None


def test_status_reader_reader_blocks_tampered_provenance_artifact(tmp_path: Path) -> None:
    doc_root = tmp_path / "alpha"
    artifact = doc_root / "output" / "v2" / "alpha.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"original")
    manifest = BuildManifest(
        document_id="alpha",
        artifacts=(ArtifactRef(str(artifact), sha256_file(artifact), ArtifactState.READY, size_bytes=artifact.stat().st_size),),
        verification={"passed": True},
        provenance_run="build-002",
    )
    manifest_path = artifact.with_suffix(".docx.manifest.json")
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedger(doc_root / "runs" / "v2-provenance.json")
    source = doc_root / "source.md"
    source.write_text("source", encoding="utf-8")
    ledger.record_run("build-002", inputs=(source,), outputs=(artifact,))
    ledger.record_attestation("build-002", manifest.attestation())

    artifact.write_bytes(b"tampered")
    snapshot = StatusReader().read(doc_root)

    assert snapshot.succeeded is False
    assert any("artifact hash mismatch" in finding for finding in snapshot.publication_blockers)
    assert any("provenance run failed integrity" in finding for finding in snapshot.publication_blockers)


def test_status_reader_reader_accepts_legacy_absolute_path_attestation(tmp_path: Path) -> None:
    doc_root = tmp_path / "alpha"
    artifact = doc_root / "output" / "v2" / "alpha.docx"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"original")
    manifest = BuildManifest(
        document_id="alpha",
        artifacts=(ArtifactRef(str(artifact), sha256_file(artifact), ArtifactState.READY),),
        verification={"passed": True},
        provenance_run="build-legacy",
    )
    manifest_path = artifact.with_suffix(".docx.manifest.json")
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedger(doc_root / "runs" / "v2-provenance.json")
    source = doc_root / "source.md"
    source.write_text("source", encoding="utf-8")
    ledger.record_run("build-legacy", inputs=(source,), outputs=(artifact,))
    legacy = manifest.to_dict()
    legacy["artifacts"][0]["media_type"] = "application/octet-stream"
    legacy["artifacts"][0]["size_bytes"] = artifact.stat().st_size
    ledger.record_attestation(
        "build-legacy",
        {
            "schema": "docs.attestation/v2",
            "manifest": legacy,
            "sha256": sha256_content(legacy),
        },
    )

    snapshot = StatusReader().read(doc_root)

    assert snapshot.succeeded is True
    assert not any("provenance attestation mismatch" in finding for finding in snapshot.publication_blockers)


def test_status_reader_manifest_selection_ignores_mtime(tmp_path: Path) -> None:
    output = tmp_path / "output" / "v2"
    output.mkdir(parents=True)
    first = BuildManifest(document_id="first")
    second = BuildManifest(document_id="second")
    first_path = output / "first.docx.manifest.json"
    second_path = output / "second.docx.manifest.json"
    first_path.write_text(first.to_json(), encoding="utf-8")
    second_path.write_text(second.to_json(), encoding="utf-8")
    expected = max((first.identity(), first_path.as_posix()), (second.identity(), second_path.as_posix()))[1]

    first_path.touch()
    second_path.touch()

    assert StatusReader._latest_manifest_path(tmp_path) == Path(expected)



