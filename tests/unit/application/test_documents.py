# tests/unit/application/test_documents.py
"""Unit coverage for DocumentService.create() workspace bootstrap (spec:
document-pipeline "Document Workspace Creation Includes Ingest Inbox").
Uses a lightweight fake repository/workspace instead of the filesystem
adapter -- exercises `_SUBDIRS` in isolation (see
tests/integration/test_document_service.py for the repository-backed
integration coverage of the rest of DocumentService)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from docs.application.documents import DocumentService
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest
from docs.domain.models.document import DocumentSummary
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace


class _NarrowPortFake:
    """Same minimal fake as test_document_service.py's
    `_NarrowPortFake` -- satisfies ONLY `RegistryRepository`/
    `DocumentRepository`/`TemplateRepository`."""

    def __init__(self) -> None:
        self.documents: dict[str, object] = {}
        self.active = ""

    def load_registry(self):
        raise NotImplementedError

    def save_registry(self, registry) -> None:
        raise NotImplementedError

    def active_id(self) -> str:
        return self.active

    def set_active(self, doc_id: str) -> None:
        self.active = doc_id

    def register(self, summary: DocumentSummary) -> None:
        self.documents[summary.id] = summary

    def read_document(self, doc_id: str):
        return self.documents[doc_id]

    def write_document(self, document) -> None:
        self.documents[document.id] = document

    def exists(self, doc_id: str) -> bool:
        return doc_id in self.documents

    def move(self, old_id: str, new_id: str) -> None:
        raise NotImplementedError

    def remove(self, doc_id: str) -> None:
        raise NotImplementedError

    def load_template(self, name: str) -> Template:
        return Template(type="generic", title="Fake Template")

    def list_templates(self) -> list[str]:
        return ["fake"]


def test_create_creates_inbox_directory(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    document = service.create("alpha", "fake")

    assert document.id == "alpha"
    assert (ws.doc_root("alpha") / "inbox").is_dir()


def test_create_creates_inbox_assets_directory(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    service.create("alpha", "fake")

    assert (ws.doc_root("alpha") / "inbox" / "assets").is_dir()


def test_create_still_creates_previously_existing_subdirectories(tmp_path: Path):
    # Regression guard: adding inbox/ must not drop any subdirectory that
    # already existed before this change.
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    service.create("alpha", "fake")

    for sub in ("context", "assets", "sections", "output/draft", "output/final", "output/qa", "runs", "corrections/inbox"):
        assert (ws.doc_root("alpha") / sub).is_dir()


# --- Phase 6: lifecycle (item F, spec: document-lifecycle) -----------------


def test_create_defaults_lifecycle_to_draft(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)

    document = service.create("alpha", "fake")

    assert document.lifecycle == "draft"


def test_mark_final_sets_lifecycle_to_final(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)
    service.create("alpha", "fake")

    document = service.mark_final("alpha")

    assert document.lifecycle == "final"
    assert service.repository.read_document("alpha").lifecycle == "final"


def test_mark_final_promotes_draft_build_artifacts_to_output_final(tmp_path: Path):
    # Fresh-context robustness gap: `mark_final` set the lifecycle flag but
    # never populated `output/final/`, so `doc status`'s `output_final_exists`
    # (status.py) could never become true. A published snapshot is a COPY of
    # whatever the current draft build produced -- draft stays untouched,
    # so a later re-build still reflects "draft" honestly.
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)
    service.create("alpha", "fake")
    draft_dir = ws.doc_root("alpha") / "output" / "draft"
    (draft_dir / "tesina-draft.docx").write_bytes(b"fake docx bytes")
    (draft_dir / "tesina-draft.html").write_text("<html></html>", encoding="utf-8")

    service.mark_final("alpha")

    final_dir = ws.doc_root("alpha") / "output" / "final"
    assert (final_dir / "tesina-draft.docx").read_bytes() == b"fake docx bytes"
    assert (final_dir / "tesina-draft.html").read_text(encoding="utf-8") == "<html></html>"
    # Draft artifacts are untouched -- promotion copies, never moves.
    assert (draft_dir / "tesina-draft.docx").exists()


def test_mark_final_with_no_draft_build_warns_and_does_not_crash(tmp_path: Path, capsys):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)
    service.create("alpha", "fake")

    document = service.mark_final("alpha")

    assert document.lifecycle == "final"
    final_dir = ws.doc_root("alpha") / "output" / "final"
    assert not any(final_dir.iterdir())
    captured = capsys.readouterr()
    assert "alpha" in captured.err
    assert "borrador" in captured.err.lower() or "draft" in captured.err.lower()


def test_mark_final_promotes_only_attested_v2_artifacts_and_replaces_stale_final(
    tmp_path: Path,
):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)
    service.create("alpha", "fake")
    root = ws.doc_root("alpha")
    v2_dir = root / "output" / "v2"
    v2_dir.mkdir(parents=True, exist_ok=True)
    artifact = v2_dir / "alpha.docx"
    artifact.write_bytes(b"attested v2")
    manifest = BuildManifest(
        document_id="alpha",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "e" * 64},
            artifacts=(
                ArtifactRef(
                    str(artifact.resolve()),
                    hashlib.sha256(b"attested v2").hexdigest(),
                    ArtifactState.READY,
                ),
            ),
        verification={"passed": True},
        provenance_run="v2-run",
    )
    manifest_path = artifact.with_suffix(".docx.manifest.json")
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(root / "runs" / "v2-provenance.json", trusted_root=root)
    ledger.record_run("v2-run", inputs=(artifact,), outputs=(artifact,))
    ledger.record_attestation("v2-run", manifest.attestation())
    stale = root / "output" / "final" / "stale.docx"
    stale.write_bytes(b"stale")

    service.mark_final("alpha")

    final_dir = root / "output" / "final"
    assert (final_dir / artifact.name).read_bytes() == b"attested v2"
    assert (final_dir / manifest_path.name).read_text(encoding="utf-8") == manifest_path.read_text(encoding="utf-8")
    assert not stale.exists()


def test_mark_final_rejects_tampered_v2_artifact_without_touching_final(
    tmp_path: Path,
):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    service = DocumentService(_NarrowPortFake(), ws)
    service.create("alpha", "fake")
    root = ws.doc_root("alpha")
    v2_dir = root / "output" / "v2"
    v2_dir.mkdir(parents=True, exist_ok=True)
    artifact = v2_dir / "alpha.docx"
    original = b"attested v2"
    artifact.write_bytes(original)
    manifest = BuildManifest(
        document_id="alpha",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "e" * 64},
        artifacts=(
            ArtifactRef(
                str(artifact.resolve()),
                hashlib.sha256(original).hexdigest(),
                ArtifactState.READY,
            ),
        ),
        verification={"passed": True},
        provenance_run="v2-run",
    )
    manifest_path = artifact.with_suffix(".docx.manifest.json")
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(root / "runs" / "v2-provenance.json", trusted_root=root)
    ledger.record_run("v2-run", inputs=(artifact,), outputs=(artifact,))
    ledger.record_attestation("v2-run", manifest.attestation())
    final_dir = root / "output" / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    stale = final_dir / "stale.docx"
    stale.write_bytes(b"stale")
    artifact.write_bytes(b"tampered")

    try:
        service.mark_final("alpha")
    except RuntimeError as exc:
        assert "publication validation" in str(exc)
    else:
        raise AssertionError("tampered v2 artifact was published")

    assert stale.read_bytes() == b"stale"
