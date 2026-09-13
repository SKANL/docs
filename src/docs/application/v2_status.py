"""Read-only v2 build observability for document status consumers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.domain.artifacts import BuildManifest


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
        manifests = sorted(
            (document_root / "output" / "v2").glob("*.manifest.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        return manifests[0] if manifests else None

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
        return V2Status(
            manifest=manifest,
            capabilities=capabilities,
            execution=execution,
            provenance=provenance,
            succeeded=succeeded,
            unsupported_stages=unsupported_stages,
            publication_blockers=publication_blockers,
        )


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
