"""Validate and publish verified document package artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from docs.application.atomic_transform import AtomicTransform, TransformSpec
from docs.application.package_service import PackageFile, PackagePublicationError, PackageService
from docs.application.provenance import ProvenanceLedger
from docs.domain.artifacts import BuildManifest
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy


@dataclass(frozen=True)
class PublicationResult:
    """The artifact and manifest paths atomically published for release."""

    artifact: Path
    manifest: Path
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PreparedPublication:
    """Immutable publish evidence captured before resolving live build inputs."""

    document_root: Path
    source: Path
    destination: Path
    manifest_path: Path
    manifest: BuildManifest
    source_bytes: bytes
    manifest_bytes: bytes
    attestation_sha256: str


@dataclass(frozen=True)
class FileSnapshot:
    """Bytes and non-following filesystem identity captured from one input."""

    content: bytes
    mode: int
    device: int
    inode: int

    @property
    def identity(self) -> FileIdentity:
        return FileIdentity(self.mode, self.device, self.inode, hashlib.sha256(self.content).hexdigest())


@dataclass(frozen=True)
class FileIdentity:
    """Bounded-memory identity used to revalidate a captured input."""

    mode: int
    device: int
    inode: int
    sha256: str


@dataclass(frozen=True)
class PackageSourceFile:
    """A package member bound to the identity of the file it was read from."""

    relative_path: str
    snapshot: FileSnapshot


class PackagePublicationService:
    """Own package input validation, deterministic archives, and release copies."""

    def __init__(
        self,
        *,
        archive_writer: PackageService,
        lock: Callable[[Path], AbstractContextManager[None]],
    ) -> None:
        self._archive_writer = archive_writer
        self._lock = lock

    def package(
        self,
        output: Path,
        source_dir: Path,
        *,
        allow_staging: bool = False,
        verify_attestation: bool = True,
        lock_held: bool = False,
    ) -> None:
        """Validate a complete current-output set and atomically write its archive."""
        with nullcontext() if lock_held else self._lock(output.with_name(output.name + ".lock")):
            files = self._package_files(
                source_dir,
                allow_staging=allow_staging,
                verify_attestation=verify_attestation,
            )
            if not self._source_snapshot_is_current(files, source_dir):
                raise PackagePublicationError("package source changed before archive write")
            self._archive_writer.write(
                output,
                tuple(PackageFile(file.relative_path, file.snapshot.content) for file in files),
                lock_held=True,
            )

    def publish(
        self,
        prepared: PreparedPublication,
        *,
        current_identities: Mapping[str, object],
    ) -> PublicationResult:
        """Publish exactly the immutable evidence captured by ``preflight_publish``."""
        self._validate_current_identities(prepared.manifest, current_identities)
        attestation = prepared.manifest.attestation()
        if str(attestation["sha256"]) != prepared.attestation_sha256:
            raise PackagePublicationError("publish preflight attestation no longer matches its manifest")
        ledger = ProvenanceLedger(
            prepared.document_root / "runs" / "provenance.json", trusted_root=prepared.document_root
        )
        if not ledger.verify_attestation(prepared.manifest.provenance_run or "", attestation):
            raise PackagePublicationError("publish requires a present, verifiable provenance attestation")
        destination_manifest = prepared.destination.with_suffix(prepared.destination.suffix + ".manifest.json")

        def write_publication(scratch: Path) -> None:
            (scratch / "artifact").write_bytes(prepared.source_bytes)
            (scratch / "manifest").write_bytes(prepared.manifest_bytes)

        publication = AtomicTransform().run(
            TransformSpec(
                expected_outputs=("artifact", "manifest"),
                destinations=(prepared.destination, destination_manifest),
            ),
            write_publication,
        )
        if not publication.ok:
            raise PackagePublicationError(f"publish failed: {publication.error}")
        return PublicationResult(prepared.destination, destination_manifest, tuple(publication.warnings))

    def preflight_publish(
        self, source: Path, destination: Path, *, policy: PipelineMode
    ) -> PreparedPublication:
        """Capture and validate publish evidence before resolving current build inputs."""
        if not PipelinePolicy(policy).can_publish():
            raise PackagePublicationError("publish requires --policy strict or --policy release")
        document_root = source.parent.parent.parent
        manifest_path = source.with_suffix(source.suffix + ".manifest.json")
        if source.parent.name != "current" or source.parent.parent.name != "output":
            raise PackagePublicationError("publish requires an artifact with its matching manifest")
        self._require_contained(source, document_root / "output" / "current", "source")
        self._require_contained(manifest_path, document_root / "output" / "current", "manifest")
        if not manifest_path.is_file():
            raise PackagePublicationError("publish requires an artifact with its matching manifest")
        self._require_contained(destination, document_root, "destination")
        try:
            manifest_bytes = self._read_file(manifest_path, document_root)
            manifest = BuildManifest.from_dict(json.loads(manifest_bytes.decode(encoding="utf-8")))
            manifest.validate_for_publication()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise PackagePublicationError(f"publish requires a valid manifest: {exc}") from exc
        source_bytes = self._read_file(source, document_root)
        matching = [artifact for artifact in manifest.artifacts if artifact.path == str(source.resolve())]
        if len(matching) != 1 or matching[0].sha256 != hashlib.sha256(source_bytes).hexdigest():
            raise PackagePublicationError("publish requires the manifest artifact hash to match the source")
        attestation = manifest.attestation()
        ledger = ProvenanceLedger(document_root / "runs" / "provenance.json", trusted_root=document_root)
        if not ledger.verify_attestation(manifest.provenance_run or "", attestation):
            raise PackagePublicationError("publish requires a present, verifiable provenance attestation")
        return PreparedPublication(
            document_root=document_root,
            source=source,
            destination=destination,
            manifest_path=manifest_path,
            manifest=manifest,
            source_bytes=source_bytes,
            manifest_bytes=manifest_bytes,
            attestation_sha256=str(attestation["sha256"]),
        )

    def _package_files(
        self, source_dir: Path, *, allow_staging: bool, verify_attestation: bool
    ) -> tuple[PackageSourceFile, ...]:
        valid_source = source_dir.name == "current" and source_dir.parent.name == "output"
        valid_staging = allow_staging and source_dir.name.startswith(".x20-package-") and source_dir.parent.name == "output"
        if not (valid_source or valid_staging):
            raise PackagePublicationError("package requires an output/current source directory")
        if any(path.is_symlink() for path in (source_dir, *source_dir.parents)):
            raise PackagePublicationError("package refuses a symlinked source boundary")
        files = self._source_files(source_dir)
        artifacts = tuple(path for path in files if not path.name.endswith(".manifest.json"))
        if not artifacts:
            raise PackagePublicationError("package requires at least one artifact")
        document_root = source_dir.parent.parent
        ledger = ProvenanceLedger(document_root / "runs" / "provenance.json", trusted_root=document_root)
        expected_manifests: set[Path] = set()
        snapshots: dict[str, FileSnapshot] = {}
        generation_identity: tuple[tuple[object, ...], dict[str, tuple[tuple[str, str], ...]]] | None = None
        for artifact in artifacts:
            manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
            if not manifest_path.is_file():
                raise PackagePublicationError(f"package requires a matching manifest for {artifact.name}")
            try:
                artifact_snapshot = self._read_snapshot(artifact, document_root)
                manifest_snapshot = self._read_snapshot(manifest_path, document_root)
                manifest = BuildManifest.from_dict(
                    json.loads(manifest_snapshot.content.decode(encoding="utf-8"))
                )
                manifest.validate_for_publication()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise PackagePublicationError(f"package requires a valid manifest for {artifact.name}: {exc}") from exc
            digest = hashlib.sha256(artifact_snapshot.content).hexdigest()
            matching = [entry for entry in manifest.artifacts if entry.path == str(artifact.resolve()) or (allow_staging and entry.sha256 == digest)]
            if len(matching) != 1 or matching[0].sha256 != digest:
                raise PackagePublicationError(f"package requires the manifest artifact hash to match {artifact.name}")
            if verify_attestation and not ledger.verify_attestation(manifest.provenance_run or "", manifest.attestation()):
                raise PackagePublicationError(f"package requires a verifiable provenance attestation for {artifact.name}")
            shared_identity = (manifest.document_id, manifest.source_hash, manifest.template_hash, manifest.template_ir_hash, manifest.config_hash, manifest.context_hash, tuple(sorted(manifest.asset_hashes.items())))
            format_name = artifact.suffix.lstrip(".")
            renderer_identity = tuple(sorted(manifest.renderer_versions.items()))
            if generation_identity is None:
                generation_identity = (shared_identity, {format_name: renderer_identity})
            elif shared_identity != generation_identity[0]:
                raise PackagePublicationError(f"package refuses mixed source generation for {artifact.name}")
            elif format_name in generation_identity[1] and renderer_identity != generation_identity[1][format_name]:
                raise PackagePublicationError(f"package refuses mixed renderer generation for {artifact.name}")
            else:
                generation_identity[1][format_name] = renderer_identity
            expected_manifests.add(manifest_path)
            snapshots[artifact.relative_to(source_dir).as_posix()] = artifact_snapshot
            snapshots[manifest_path.relative_to(source_dir).as_posix()] = manifest_snapshot
        actual_manifests = {path for path in files if path.name.endswith(".manifest.json")}
        if actual_manifests != expected_manifests:
            raise PackagePublicationError("package requires each manifest to match one artifact")
        return tuple(PackageSourceFile(relative, snapshots[relative]) for relative in sorted(snapshots))

    @staticmethod
    def _source_files(source_dir: Path) -> tuple[Path, ...]:
        candidates = tuple(
            sorted(source_dir.rglob("*"), key=lambda path: path.relative_to(source_dir).as_posix())
        )
        unsafe = next((path for path in candidates if path.is_symlink()), None)
        if unsafe is not None:
            raise PackagePublicationError(f"package refuses symlinked path: {unsafe.name}")
        return tuple(path for path in candidates if path.is_file() and not path.is_symlink())

    def _source_snapshot_is_current(
        self, files: tuple[PackageSourceFile, ...], source_dir: Path
    ) -> bool:
        try:
            current = {
                path.relative_to(source_dir).as_posix(): path for path in self._source_files(source_dir)
            }
        except (OSError, ValueError, PackagePublicationError):
            return False
        expected = {file.relative_path: file.snapshot.identity for file in files}
        if set(current) != set(expected):
            return False
        document_root = source_dir.parent.parent
        try:
            return all(
                self._stream_identity(path, document_root) == expected[relative]
                for relative, path in current.items()
            )
        except (OSError, PackagePublicationError):
            return False

    @staticmethod
    def _validate_current_identities(manifest: BuildManifest, current: Mapping[str, object]) -> None:
        for field, label in (("template_hash", "template"), ("template_ir_hash", "template IR"), ("config_hash", "config"), ("context_hash", "context"), ("asset_hashes", "asset"), ("renderer_versions", "renderer"), ("source_hash", "source inputs")):
            if field == "template_ir_hash" and not getattr(manifest, field):
                continue
            if current[field] != getattr(manifest, field):
                raise PackagePublicationError(f"publish requires unchanged {label} identity")

    @staticmethod
    def _require_contained(path: Path, root: Path, label: str) -> None:
        if any(candidate.is_symlink() for candidate in (path, *path.parents)):
            raise PackagePublicationError(f"publish refuses symlinked {label}: {path.name}")
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError as exc:
            raise PackagePublicationError(f"publish {label} path escapes its intended root") from exc

    @staticmethod
    def _read_file(path: Path, document_root: Path) -> bytes:
        return PackagePublicationService._read_snapshot(path, document_root).content

    @staticmethod
    def _read_snapshot(path: Path, document_root: Path) -> FileSnapshot:
        try:
            path.resolve(strict=True).relative_to(document_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise PackagePublicationError(f"package file escapes document root: {path.name}") from exc
        if any(candidate.is_symlink() for candidate in (path, *path.parents)):
            raise PackagePublicationError(f"package refuses symlinked path: {path.name}")
        resolved = path.resolve(strict=True)
        ancestors = tuple((ancestor, (os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino)) for ancestor in (document_root, *path.parents) if ancestor.exists())
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise PackagePublicationError(f"package refuses unsafe file: {path.name}: {exc}") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode) or path.is_symlink():
                raise PackagePublicationError(f"package requires a regular non-symlink file: {path.name}")
            if any((os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino) != identity for ancestor, identity in ancestors):
                raise PackagePublicationError(f"package path boundary changed while reading: {path.name}")
            opened, expected = os.fstat(descriptor), os.stat(resolved, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
                raise PackagePublicationError(f"package input changed while reading: {path.name}")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return FileSnapshot(
                    content=handle.read(),
                    mode=opened.st_mode,
                    device=opened.st_dev,
                    inode=opened.st_ino,
                )
        finally:
            if descriptor != -1:
                os.close(descriptor)

    @staticmethod
    def _stream_identity(path: Path, document_root: Path) -> FileIdentity:
        try:
            path.resolve(strict=True).relative_to(document_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise PackagePublicationError(f"package file escapes document root: {path.name}") from exc
        if any(candidate.is_symlink() for candidate in (path, *path.parents)):
            raise PackagePublicationError(f"package refuses symlinked path: {path.name}")
        resolved = path.resolve(strict=True)
        ancestors = tuple(
            (ancestor, (os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino))
            for ancestor in (document_root, *path.parents)
            if ancestor.exists()
        )
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            raise PackagePublicationError(f"package refuses unsafe file: {path.name}: {exc}") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or path.is_symlink():
                raise PackagePublicationError(f"package requires a regular non-symlink file: {path.name}")
            if any(
                (os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino) != identity
                for ancestor, identity in ancestors
            ):
                raise PackagePublicationError(f"package path boundary changed while reading: {path.name}")
            expected = os.stat(resolved, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
                raise PackagePublicationError(f"package input changed while reading: {path.name}")
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            return FileIdentity(opened.st_mode, opened.st_dev, opened.st_ino, digest.hexdigest())
        finally:
            if descriptor != -1:
                os.close(descriptor)
