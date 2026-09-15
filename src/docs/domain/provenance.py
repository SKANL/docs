from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from docs.domain.artifacts import ArtifactRef, ArtifactState

_SCHEMA = "docs.provenance/v1"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact(value: dict[str, Any], state: ArtifactState) -> ArtifactRef:
    return ArtifactRef(
        path=str(value.get("path", "")),
        sha256=str(value.get("sha256", "")),
        state=ArtifactState(value.get("state", state.value)),
    )


def _entry_content(operation: str, inputs: list[ArtifactRef], outputs: list[ArtifactRef]) -> dict[str, object]:
    return {
        "inputs": [artifact.to_dict() for artifact in inputs],
        "operation": operation,
        "outputs": [artifact.to_dict() for artifact in outputs],
    }


@dataclass(frozen=True)
class ProvenanceEntry:
    operation: str
    inputs: list[ArtifactRef]
    outputs: list[ArtifactRef]
    sha256: str

    @classmethod
    def create(cls, operation: str, inputs: list[ArtifactRef], outputs: list[ArtifactRef]) -> ProvenanceEntry:
        content = _entry_content(operation, inputs, outputs)
        return cls(operation=operation, inputs=inputs, outputs=outputs, sha256=_sha256(content))

    def to_dict(self) -> dict[str, object]:
        return {**_entry_content(self.operation, self.inputs, self.outputs), "sha256": self.sha256}


@dataclass(frozen=True)
class ProvenanceLedger:
    entries: list[ProvenanceEntry]

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]]) -> ProvenanceLedger:
        return cls(entries=[cls._parse_entry(entry) for entry in entries])

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProvenanceLedger:
        if payload.get("schema") == _SCHEMA:
            return cls.from_entries(list(payload.get("entries", [])))
        return cls(entries=[cls._parse_current_entry(entry) for entry in payload.get("events", [])])

    @staticmethod
    def _parse_entry(value: dict[str, Any]) -> ProvenanceEntry:
        inputs = [_artifact(item, ArtifactState.READY) for item in value.get("inputs", [])]
        outputs = [_artifact(item, ArtifactState.PUBLISHED) for item in value.get("outputs", [])]
        operation = str(value.get("operation", ""))
        expected = _sha256(_entry_content(operation, inputs, outputs))
        return ProvenanceEntry(operation, inputs, outputs, str(value.get("sha256", expected)))

    @staticmethod
    def _parse_current_entry(value: dict[str, Any]) -> ProvenanceEntry:
        inputs = [ArtifactRef(path=str(value["input"]), sha256="", state=ArtifactState.READY)] if "input" in value else []
        outputs = [ArtifactRef(path=str(value["output"]), sha256="", state=ArtifactState.PUBLISHED)] if "output" in value else []
        return ProvenanceEntry.create(str(value.get("action", value.get("operation", ""))), inputs, outputs)

    def to_dict(self) -> dict[str, object]:
        return {"entries": [entry.to_dict() for entry in self.entries], "schema": _SCHEMA}

    def verify(self, payload: dict[str, Any] | None = None) -> list[str]:
        document = self.to_dict() if payload is None else payload
        if document.get("schema") != _SCHEMA:
            return ["schema must be docs.provenance/v1"]
        entries = document.get("entries", [])
        if not isinstance(entries, list):
            return ["entries must be a list"]
        findings: list[str] = []
        for index, value in enumerate(entries):
            if not isinstance(value, dict):
                findings.append(f"entries[{index}] must be an object")
                continue
            inputs = [_artifact(item, ArtifactState.READY) for item in value.get("inputs", [])]
            outputs = [_artifact(item, ArtifactState.PUBLISHED) for item in value.get("outputs", [])]
            expected = _sha256(_entry_content(str(value.get("operation", "")), inputs, outputs))
            if value.get("sha256") != expected:
                findings.append(f"entries[{index}].sha256 does not match entry content")
        return findings
