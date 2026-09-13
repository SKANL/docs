from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_content
from docs.domain.models.document import Document, DocumentSummary
from docs.domain.ports.document_repository import DocumentExistsError, DocumentRepository
from docs.domain.ports.registry_repository import RegistryRepository
from docs.domain.ports.template_repository import TemplateRepository
from docs.domain.slug import validate_slug
from docs.domain.workspace import Workspace


class DocumentLifecycleRepository(RegistryRepository, DocumentRepository, TemplateRepository, Protocol):
    """Composed port for `DocumentService`: its lifecycle operations
    (create/list/current/use/rename/delete) genuinely span registry,
    document-content, and template access, so it depends on the union of
    the three narrow ports rather than reintroducing one fat protocol.
    Narrower consumers (e.g. `ContextService`) depend on just
    `DocumentRepository`."""


_SUBDIRS = (
    "context", "assets", "sections",
    "output/draft", "output/final", "output/qa",
    "runs", "corrections/inbox",
    # spec: document-pipeline "Document Workspace Creation Includes Ingest
    # Inbox" -- inbox/assets/ is created here too (front:assets-figures owns
    # its contents, but bootstrap owns _SUBDIRS).
    "inbox", "inbox/assets",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DocumentService:
    def __init__(
        self,
        repository: DocumentLifecycleRepository,
        workspace: Workspace,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self._clock = clock

    def create(self, doc_id: str, template_name: str, title: str = "") -> Document:
        validate_slug(doc_id)
        template = self.repository.load_template(template_name)
        if self.repository.exists(doc_id):
            raise DocumentExistsError(f"Document `{doc_id}` already exists.")
        doc_root = self.workspace.doc_root(doc_id)
        for sub in _SUBDIRS:
            (doc_root / sub).mkdir(parents=True, exist_ok=True)
        document = Document(
            id=doc_id,
            title=title or template.title or doc_id,
            template=template_name,
            project=dict(template.project_defaults),
            structure=list(template.structure),
            overrides={},
        )
        self.repository.write_document(document)
        self.repository.register(
            DocumentSummary(
                id=doc_id, title=document.title,
                template=template_name, created_at=self._clock(),
            )
        )
        return document

    def list(self) -> list[DocumentSummary]:
        return self.repository.load_registry().documents

    def current(self) -> str:
        return self.repository.active_id()

    def use(self, doc_id: str) -> None:
        validate_slug(doc_id)
        self.repository.set_active(doc_id)

    def rename(self, doc_id: str, new_id: str) -> None:
        validate_slug(doc_id)
        validate_slug(new_id)
        self.repository.move(doc_id, new_id)

    def delete(self, doc_id: str) -> None:
        validate_slug(doc_id)
        self.repository.remove(doc_id)

    def mark_final(self, doc_id: str) -> Document:
        """Lifecycle-lite (design.md item F): user-set `final` marker, no
        heavier VCS/workflow. Read-modify-write through the same port
        `write_document` already uses elsewhere in this class. Also PROMOTES
        the current draft build (`output/draft/`) into `output/final/` -- a
        published snapshot COPY, so `doc status`'s `output_final_exists`
        (status.py) becomes meaningful and a later re-build still honestly
        reflects "draft" until finalized again."""
        validate_slug(doc_id)
        document = self.repository.read_document(doc_id)
        if self._has_v2_build(doc_id):
            self._promote_v2_to_final(doc_id)
        updated = document.model_copy(update={"lifecycle": "final"})
        self.repository.write_document(updated)
        if not self._has_v2_build(doc_id):
            self._promote_draft_to_final(doc_id)
        return updated

    def _has_v2_build(self, doc_id: str) -> bool:
        v2_dir = self.workspace.doc_root(doc_id) / "output" / "v2"
        return v2_dir.is_dir() and any(
            path.is_file() and not path.name.endswith(".manifest.json")
            for path in v2_dir.iterdir()
        )

    def _promote_v2_to_final(self, doc_id: str) -> None:
        """Promote only a complete, attested v2 artifact set atomically."""
        root = self.workspace.doc_root(doc_id)
        v2_dir = root / "output" / "v2"
        artifacts = tuple(
            sorted(
                (
                    path
                    for path in v2_dir.iterdir()
                    if path.is_file() and not path.name.endswith(".manifest.json")
                ),
                key=lambda path: path.name,
            )
        )
        if not artifacts:
            raise RuntimeError(f"v2 build for `{doc_id}` contains no artifacts")
        ledger = ProvenanceLedgerV2(root / "runs" / "v2-provenance.json", trusted_root=root)
        validated: list[tuple[Path, Path]] = []
        for artifact in artifacts:
            manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
            if not manifest_path.is_file() or manifest_path.is_symlink():
                raise RuntimeError(f"v2 artifact `{artifact.name}` has no manifest")
            try:
                manifest = BuildManifest.from_dict(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
                manifest.validate_for_publication()
                matching = [
                    entry
                    for entry in manifest.artifacts
                    if entry.path == str(artifact.resolve())
                ]
                if (
                    manifest.document_id != doc_id
                    or len(matching) != 1
                    or matching[0].sha256
                    != hashlib.sha256(artifact.read_bytes()).hexdigest()
                    or not self._verify_v2_attestation(ledger, manifest)
                ):
                    raise ValueError("manifest, artifact, or provenance does not match")
            except (OSError, TypeError, ValueError, KeyError, IndexError) as exc:
                raise RuntimeError(
                    f"v2 artifact `{artifact.name}` failed publication validation: {exc}"
                ) from exc
            validated.append((artifact, manifest_path))

        output_parent = root / "output"
        final_dir = output_parent / "final"
        staging = Path(tempfile.mkdtemp(prefix=".final-v2-", dir=output_parent))
        backup = output_parent / f".final-backup-{os.getpid()}"
        try:
            for artifact, manifest_path in validated:
                shutil.copyfile(artifact, staging / artifact.name)
                shutil.copyfile(manifest_path, staging / manifest_path.name)
            if final_dir.exists():
                if final_dir.is_symlink():
                    raise RuntimeError("output/final must not be a symlink")
                os.replace(final_dir, backup)
            os.replace(staging, final_dir)
            if backup.exists():
                shutil.rmtree(backup)
        except Exception:
            if final_dir.exists() and not backup.exists():
                shutil.rmtree(final_dir)
            if backup.exists() and not final_dir.exists():
                os.replace(backup, final_dir)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _verify_v2_attestation(ledger: ProvenanceLedgerV2, manifest: BuildManifest) -> bool:
        """Accept old v2 manifests that predate optional artifact metadata."""
        if ledger.verify_attestation(manifest.provenance_run or "", manifest.attestation()):
            return True
        recorded = ledger.load_attestation(manifest.provenance_run or "")
        if not isinstance(recorded, dict):
            return False
        recorded_manifest = recorded.get("manifest")
        if not isinstance(recorded_manifest, dict):
            return False
        if recorded.get("sha256") != sha256_content(recorded_manifest):
            return False
        current = manifest.to_dict()
        recorded_artifacts = recorded_manifest.get("artifacts", [])
        current_artifacts = current.get("artifacts", [])
        if not isinstance(recorded_artifacts, list) or not isinstance(current_artifacts, list):
            return False
        for item in (recorded_artifacts, current_artifacts):
            for artifact in item:
                if isinstance(artifact, dict):
                    artifact.pop("media_type", None)
                    artifact.pop("size_bytes", None)
        return recorded_manifest == current

    def _promote_draft_to_final(self, doc_id: str) -> None:
        doc_root = self.workspace.doc_root(doc_id)
        draft_dir = doc_root / "output" / "draft"
        final_dir = doc_root / "output" / "final"
        draft_files = [p for p in draft_dir.iterdir() if p.is_file()] if draft_dir.is_dir() else []
        if not draft_files:
            print(
                f"WARN: `{doc_id}` no tiene un build en borrador (output/draft "
                "vacío); no hay nada que promover a output/final.",
                file=sys.stderr,
            )
            return
        final_dir.mkdir(parents=True, exist_ok=True)
        for path in draft_files:
            shutil.copyfile(path, final_dir / path.name)
