"""Read-only inspection for supported workspace migration sources.

This module is the only application boundary that knows the evidenced legacy
workspace shape.  Inspection snapshots every source file as raw bytes before
it parses any format record, and it never creates migration state or layout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from docs.domain.ports.registry_repository import Registry
from docs.domain.workspace_format import WorkspaceFormatError, validate_workspace_marker

CANONICAL_FORMAT = "docs.workspace/v1"
CURRENT_UNVERSIONED_FORMAT = "current-unversioned"
UNKNOWN_FORMAT = "unknown"

Disposition = Literal["preserved", "omitted", "excluded", "unknown"]


@dataclass(frozen=True)
class MigrationRecord:
    """One immutable raw source record and its migration disposition."""

    path: str
    size: int
    sha256: str
    disposition: Disposition = "unknown"


@dataclass(frozen=True)
class MigrationInspectionError:
    """A deterministic source-inspection failure with raw evidence."""

    code: str
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class WorkspaceMigrationInspection:
    """The complete report-only result for one rooted source workspace."""

    source_root: Path
    destination: Path | None
    detected_format: str
    records: tuple[MigrationRecord, ...]
    errors: tuple[MigrationInspectionError, ...]
    transformations: tuple[str, ...]
    publication_policy: str = "separate-absent-destination"
    recovery_guidance: str = "source-remains-unchanged-until-explicit-cutover"

    @property
    def ready(self) -> bool:
        return self.detected_format != UNKNOWN_FORMAT and not self.errors and not self.unknown

    @property
    def preserved(self) -> tuple[MigrationRecord, ...]:
        return self._records_with("preserved")

    @property
    def omitted(self) -> tuple[MigrationRecord, ...]:
        return self._records_with("omitted")

    @property
    def excluded(self) -> tuple[MigrationRecord, ...]:
        return self._records_with("excluded")

    @property
    def unknown(self) -> tuple[MigrationRecord, ...]:
        return self._records_with("unknown")

    def record(self, path: str) -> MigrationRecord:
        normalized = Path(path).as_posix()
        try:
            return next(record for record in self.records if record.path == normalized)
        except StopIteration as exc:
            raise KeyError(normalized) from exc

    def _records_with(self, disposition: Disposition) -> tuple[MigrationRecord, ...]:
        return tuple(record for record in self.records if record.disposition == disposition)


class WorkspaceMigrationError(RuntimeError):
    """A publication failure that never authorizes source or destination mutation."""

    def __init__(self, code: str, *, scratch_path: Path | None = None) -> None:
        self.code = code
        self.scratch_path = scratch_path
        detail = f"{code}: {scratch_path}" if scratch_path is not None else code
        super().__init__(detail)


@dataclass(frozen=True)
class WorkspaceMigrationPublication:
    """A successfully published canonical copy and its frozen source inspection."""

    inspection: WorkspaceMigrationInspection
    destination: Path
    published: bool = True
    scratch_policy: str = "removed-after-atomic-publication"


class _DuplicateKeyError(ValueError):
    pass


class WorkspaceMigrationInspector:
    """Inventory and classify a rooted migration source without writing."""

    _EXCLUDED_ROOTS = frozenset({".docs", "artifacts", "assets", "baselines", "passports", "runs"})
    _OMITTED_DOCUMENT_ROOTS = frozenset(
        {".cache", "cache", "caches", "output", "package", "packages", "qa", "scratch", "temp", "tmp"}
    )
    _PRESERVED_DOCUMENT_ROOTS = frozenset(
        {"assets", "context", "evidence", "inbox", "manifests", "revisions", "sections"}
    )

    def inspect(
        self,
        source: str | Path,
        *,
        destination: str | Path | None = None,
    ) -> WorkspaceMigrationInspection:
        source_root = Path(source).expanduser().resolve()
        resolved_destination = Path(destination).expanduser().resolve() if destination is not None else None
        raw_records, raw_bytes, inventory_errors = self._inventory(source_root)
        if inventory_errors:
            return WorkspaceMigrationInspection(
                source_root=source_root,
                destination=resolved_destination,
                detected_format=UNKNOWN_FORMAT,
                records=raw_records,
                errors=inventory_errors,
                transformations=(),
            )

        detected_format, registry, format_errors = self._detect_format(source_root, raw_bytes, raw_records)
        document_ids = frozenset(summary.id for summary in registry.documents) if registry is not None else frozenset()
        records = tuple(self._classify(record, document_ids) for record in raw_records)
        errors = [*format_errors]
        errors.extend(
            MigrationInspectionError("unknown_workspace_record", record.path, record.sha256)
            for record in records
            if record.disposition == "unknown"
        )
        if detected_format != UNKNOWN_FORMAT and registry is not None:
            errors.extend(self._validate_evidenced_records(raw_bytes, registry))

        transformations = (
            ("add-canonical-workspace-marker",)
            if detected_format == CURRENT_UNVERSIONED_FORMAT and not errors
            else ()
        )
        return WorkspaceMigrationInspection(
            source_root=source_root,
            destination=resolved_destination,
            detected_format=detected_format,
            records=records,
            errors=tuple(errors),
            transformations=transformations,
        )

    @staticmethod
    def _inventory(
        root: Path,
    ) -> tuple[tuple[MigrationRecord, ...], dict[str, bytes], tuple[MigrationInspectionError, ...]]:
        if not root.is_dir():
            return (), {}, (MigrationInspectionError("workspace_source_not_directory", "."),)

        records: list[MigrationRecord] = []
        contents: dict[str, bytes] = {}
        errors: list[MigrationInspectionError] = []

        def visit(directory: Path) -> None:
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            except OSError:
                relative = directory.relative_to(root).as_posix() or "."
                errors.append(MigrationInspectionError("workspace_source_unreadable", relative))
                return
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if entry.is_symlink():
                    link_bytes = os.readlink(path).encode("utf-8", errors="surrogateescape")
                    digest = hashlib.sha256(link_bytes).hexdigest()
                    records.append(MigrationRecord(relative, len(link_bytes), digest))
                    errors.append(MigrationInspectionError("workspace_symlink_unsupported", relative, digest))
                elif entry.is_dir(follow_symlinks=False):
                    visit(path)
                elif entry.is_file(follow_symlinks=False):
                    try:
                        payload = path.read_bytes()
                    except OSError:
                        errors.append(MigrationInspectionError("workspace_source_unreadable", relative))
                        continue
                    digest = hashlib.sha256(payload).hexdigest()
                    records.append(MigrationRecord(relative, len(payload), digest))
                    contents[relative] = payload
                else:
                    errors.append(MigrationInspectionError("workspace_record_unsupported", relative))

        visit(root)
        return tuple(records), contents, tuple(errors)

    def _detect_format(
        self,
        root: Path,
        contents: dict[str, bytes],
        records: tuple[MigrationRecord, ...],
    ) -> tuple[str, Registry | None, tuple[MigrationInspectionError, ...]]:
        marker = next((record for record in records if record.path == "workspace.json"), None)
        if marker is not None:
            try:
                validate_workspace_marker(root)
            except WorkspaceFormatError as exc:
                registry, registry_error = self._parse_registry(contents, required=False)
                errors = [MigrationInspectionError(exc.code, "workspace.json", marker.sha256)]
                if registry_error is not None:
                    errors.append(registry_error)
                return (
                    UNKNOWN_FORMAT,
                    registry,
                    tuple(errors),
                )
            registry, error = self._parse_registry(contents, required=False)
            return CANONICAL_FORMAT, registry, (error,) if error is not None else ()

        registry, error = self._parse_registry(contents, required=True)
        if error is not None:
            return UNKNOWN_FORMAT, None, (error,)
        return CURRENT_UNVERSIONED_FORMAT, registry, ()

    @classmethod
    def _parse_registry(
        cls,
        contents: dict[str, bytes],
        *,
        required: bool,
    ) -> tuple[Registry | None, MigrationInspectionError | None]:
        path = "documents/registry.json"
        payload = contents.get(path)
        if payload is None:
            if required:
                return None, MigrationInspectionError("document_registry_missing", path)
            return Registry(), None
        digest = hashlib.sha256(payload).hexdigest()
        try:
            decoded = payload.decode("utf-8")
            value = json.loads(decoded, object_pairs_hook=cls._closed_object)
        except (_DuplicateKeyError, UnicodeError, json.JSONDecodeError):
            return None, MigrationInspectionError("document_registry_malformed", path, digest)
        if isinstance(value, dict) and value.get("schema", 1) != 1:
            return None, MigrationInspectionError("document_registry_unsupported", path, digest)
        try:
            registry = Registry.model_validate(value)
        except ValidationError:
            return None, MigrationInspectionError("document_registry_malformed", path, digest)
        if registry.schema_version != 1:
            return None, MigrationInspectionError("document_registry_unsupported", path, digest)
        document_ids = [summary.id for summary in registry.documents]
        if len(document_ids) != len(set(document_ids)):
            return None, MigrationInspectionError("document_registry_ambiguous", path, digest)
        if any(
            not cls._safe_component(value)
            for summary in registry.documents
            for value in (summary.id, summary.template)
        ):
            return None, MigrationInspectionError("document_registry_unsafe_path", path, digest)
        return registry, None

    @staticmethod
    def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise _DuplicateKeyError(key)
            value[key] = item
        return value

    @staticmethod
    def _safe_component(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)) and value not in {".", ".."}

    def _classify(self, record: MigrationRecord, document_ids: frozenset[str]) -> MigrationRecord:
        parts = tuple(Path(record.path).parts)
        if not parts:
            return record
        if record.path == "docs.config.json" or parts[0] in self._EXCLUDED_ROOTS:
            return replace(record, disposition="excluded")
        if record.path in {"workspace.json", "documents/registry.json"}:
            return replace(record, disposition="preserved")
        if parts[0] == "templates":
            disposition: Disposition = "preserved" if len(parts) == 2 and parts[1].endswith(".json") else "unknown"
            return replace(record, disposition=disposition)
        if len(parts) < 3 or parts[0] != "documents" or parts[1] not in document_ids:
            return record

        document_relative = parts[2:]
        if document_relative == ("document.json",):
            return replace(record, disposition="preserved")
        cache_or_scratch = {".cache", "cache", "caches", "scratch", "temp", "tmp"}
        if document_relative[0] in self._OMITTED_DOCUMENT_ROOTS or any(
            component in cache_or_scratch for component in document_relative
        ):
            return replace(record, disposition="omitted")
        if document_relative[0] in self._PRESERVED_DOCUMENT_ROOTS:
            return replace(record, disposition="preserved")
        if document_relative == ("runs", "provenance.json"):
            return replace(record, disposition="preserved")
        return record

    @staticmethod
    def _validate_evidenced_records(
        contents: dict[str, bytes],
        registry: Registry,
    ) -> tuple[MigrationInspectionError, ...]:
        errors: list[MigrationInspectionError] = []
        document_ids = {summary.id for summary in registry.documents}
        if not any(
            path.startswith("templates/") and path.endswith(".json") and path.count("/") == 1
            for path in contents
        ):
            errors.append(MigrationInspectionError("workspace_templates_missing", "templates"))
        if registry.active and registry.active not in document_ids:
            record = contents.get("documents/registry.json", b"")
            errors.append(
                MigrationInspectionError(
                    "document_registry_active_missing",
                    "documents/registry.json",
                    hashlib.sha256(record).hexdigest(),
                )
            )
        for summary in registry.documents:
            document_path = f"documents/{summary.id}/document.json"
            template_path = f"templates/{summary.template}.json"
            if document_path not in contents:
                errors.append(MigrationInspectionError("document_record_missing", document_path))
            if template_path not in contents:
                errors.append(MigrationInspectionError("document_template_missing", template_path))
        return tuple(errors)


class WorkspaceMigrationPublisher:
    """Copy an inspected workspace through a sibling scratch tree and publish atomically."""

    _MARKER_BYTES = b'{"schema":"docs.workspace/v1"}\n'

    def __init__(self, inspector: WorkspaceMigrationInspector | None = None) -> None:
        self._inspector = inspector or WorkspaceMigrationInspector()

    def publish(
        self,
        source: str | Path,
        destination: str | Path,
    ) -> WorkspaceMigrationPublication:
        source_root = Path(source).expanduser().resolve()
        destination_root = Path(destination).expanduser().resolve()
        self._validate_paths(source_root, destination_root)

        inspection = self._inspector.inspect(source_root, destination=destination_root)
        if not inspection.ready:
            raise WorkspaceMigrationError("migration_source_not_ready")

        scratch = Path(
            tempfile.mkdtemp(
                prefix=f".{destination_root.name}.migration-",
                dir=destination_root.parent,
            )
        ).resolve()
        try:
            for record in inspection.preserved:
                self._copy_record(source_root, scratch, record)
            if inspection.detected_format == CURRENT_UNVERSIONED_FORMAT:
                (scratch / "workspace.json").write_bytes(self._MARKER_BYTES)

            self._verify_source_unchanged(inspection)
            self._verify_staged_copy(inspection, scratch)
            if destination_root.exists():
                raise WorkspaceMigrationError("destination_must_be_absent")
            scratch.rename(destination_root)
        except BaseException:
            if scratch.exists():
                try:
                    shutil.rmtree(scratch)
                except OSError as cleanup_exc:
                    raise WorkspaceMigrationError(
                        "migration_scratch_cleanup_failed", scratch_path=scratch
                    ) from cleanup_exc
            raise

        return WorkspaceMigrationPublication(inspection=inspection, destination=destination_root)

    @staticmethod
    def _validate_paths(source: Path, destination: Path) -> None:
        if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
            raise WorkspaceMigrationError("destination_must_be_separate")
        if destination.exists():
            raise WorkspaceMigrationError("destination_must_be_absent")
        if not destination.parent.is_dir():
            raise WorkspaceMigrationError("destination_parent_must_exist")

    def _copy_record(self, source_root: Path, scratch: Path, record: MigrationRecord) -> None:
        source_path = source_root / record.path
        payload = source_path.read_bytes()
        if len(payload) != record.size or hashlib.sha256(payload).hexdigest() != record.sha256:
            raise WorkspaceMigrationError("migration_source_changed")
        destination_path = scratch / record.path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(payload)
        copied = destination_path.read_bytes()
        if copied != payload:
            raise WorkspaceMigrationError("migration_copy_verification_failed")

    def _verify_source_unchanged(self, original: WorkspaceMigrationInspection) -> None:
        current = self._inspector.inspect(original.source_root, destination=original.destination)
        if (
            current.detected_format != original.detected_format
            or current.records != original.records
            or current.errors != original.errors
        ):
            raise WorkspaceMigrationError("migration_source_changed")

    def _verify_staged_copy(self, source: WorkspaceMigrationInspection, scratch: Path) -> None:
        staged = self._inspector.inspect(scratch)
        if staged.detected_format != CANONICAL_FORMAT or not staged.ready:
            raise WorkspaceMigrationError("migration_staged_validation_failed")
        expected = {record.path: record.sha256 for record in source.preserved}
        if source.detected_format == CURRENT_UNVERSIONED_FORMAT:
            expected["workspace.json"] = hashlib.sha256(self._MARKER_BYTES).hexdigest()
        actual = {record.path: record.sha256 for record in staged.records}
        if actual != expected:
            raise WorkspaceMigrationError("migration_staged_verification_failed")
