"""Read-only v2 build observability for document status consumers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_content, sha256_file


@dataclass(frozen=True)
class V2Status:
    """Optional, typed observability extracted from the latest v2 build."""

    manifest: BuildManifest | None = None
    capabilities: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    succeeded: bool | None = None
    unsupported_stages: list[str] = field(default_factory=list)
    publication_blockers: list[str] = field(default_factory=list)


class V2StatusReader:
    """Fail-open reader for the latest v2 manifest and its provenance run."""

    def read(self, document_root: Path) -> V2Status:
        try:
            manifest_path = self._latest_manifest_path(document_root)
            if manifest_path is None:
                return V2Status()
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return V2Status()
            manifest = BuildManifest.from_dict(payload)
            return self._status_from_payload(document_root, manifest, payload)
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return V2Status()

    @staticmethod
    def _latest_manifest_path(document_root: Path) -> Path | None:
        candidates: list[tuple[str, str, Path]] = []
        fallback: list[Path] = []
        for path in (document_root / "output" / "v2").glob("*.manifest.json"):
            fallback.append(path)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                manifest = BuildManifest.from_dict(payload)
            except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                continue
            candidates.append((manifest.identity(), path.as_posix(), path))
        if candidates:
            return max(candidates, key=lambda item: (item[0], item[1]))[2]
        return max(fallback, key=lambda path: path.as_posix()) if fallback else None

    @staticmethod
    def _status_from_payload(
        document_root: Path, manifest: BuildManifest, payload: dict[str, Any]
    ) -> V2Status:
        report_value = payload.get("report")
        report = report_value if isinstance(report_value, Mapping) else payload
        execution_value = report.get("execution")
        execution = dict(execution_value) if isinstance(execution_value, Mapping) else payload
        capabilities_value = report.get("capabilities")
        capabilities = dict(capabilities_value) if isinstance(capabilities_value, Mapping) else None
        provenance_value = report.get("provenance")
        provenance = dict(provenance_value) if isinstance(provenance_value, Mapping) else None
        succeeded_value = report.get("succeeded")
        succeeded = succeeded_value if isinstance(succeeded_value, bool) else None
        if succeeded is None:
            passed = manifest.verification.get("passed")
            succeeded = passed if isinstance(passed, bool) else None
        if provenance is None and manifest.provenance_run:
            provenance = ProvenanceLedgerV2(document_root / "runs" / "v2-provenance.json").load_run(
                manifest.provenance_run
            )
        unsupported_stages, publication_blockers = _runtime_status_details(execution)
        publication_blockers.extend(_integrity_blockers(document_root, manifest))
        if publication_blockers and succeeded is True:
            succeeded = False
        return V2Status(
            manifest=manifest,
            capabilities=capabilities,
            execution=execution,
            provenance=provenance,
            succeeded=succeeded,
            unsupported_stages=unsupported_stages,
            publication_blockers=publication_blockers,
        )


def _integrity_blockers(document_root: Path, manifest: BuildManifest) -> list[str]:
    """Validate the immutable evidence behind a v2 status snapshot.

    Legacy manifests without a provenance run remain readable.  Once a
    manifest claims v2 provenance, however, status must not report a healthy
    build when its evidence or output bytes no longer match.
    """
    if not manifest.provenance_run:
        return []
    blockers: list[str] = []
    ledger = ProvenanceLedgerV2(document_root / "runs" / "v2-provenance.json")
    run = ledger.load_run(manifest.provenance_run)
    if run is None:
        blockers.append(f"provenance run missing: {manifest.provenance_run}")
    elif not ledger.verify_run(manifest.provenance_run):
        blockers.append(f"provenance run failed integrity verification: {manifest.provenance_run}")

    recorded = ledger.load_attestation(manifest.provenance_run)
    expected_attestation = manifest.attestation()
    if recorded is None:
        blockers.append(f"provenance attestation missing: {manifest.provenance_run}")
    elif not ledger.verify_attestation(manifest.provenance_run, expected_attestation):
        blockers.append(f"provenance attestation mismatch: {manifest.provenance_run}")
    elif recorded.get("sha256") != sha256_content(recorded.get("manifest")):
        blockers.append(f"provenance attestation hash mismatch: {manifest.provenance_run}")

    for artifact in manifest.artifacts:
        path = Path(artifact.path)
        if not path.exists():
            blockers.append(f"artifact missing: {path}")
            continue
        try:
            if sha256_file(path) != artifact.sha256:
                blockers.append(f"artifact hash mismatch: {path}")
            if artifact.size_bytes is not None and path.stat().st_size != artifact.size_bytes:
                blockers.append(f"artifact size mismatch: {path}")
        except OSError as exc:
            blockers.append(f"artifact unreadable: {path} ({exc})")
    return blockers


def _runtime_status_details(execution: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Expose runtime facts without reinterpreting the pipeline policy."""
    results = execution.get("results")
    if not isinstance(results, list):
        return [], []

    unsupported_stages: list[str] = []
    publication_blockers: list[str] = []
    for result in results:
        if not isinstance(result, Mapping):
            continue
        stage = result.get("stage")
        if not isinstance(stage, str):
            continue
        if result.get("outcome") == "unsupported" and stage not in unsupported_stages:
            unsupported_stages.append(stage)
        if stage not in {"publish", "publish-draft", "package-release"}:
            continue
        errors = result.get("errors")
        if not isinstance(errors, list):
            continue
        for error in errors:
            if isinstance(error, str) and error not in publication_blockers:
                publication_blockers.append(error)
    return unsupported_stages, publication_blockers
