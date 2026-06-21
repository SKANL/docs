# src/docs/application/evidence.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.evidence import ManualFileFact, TraceabilityFact, build_manifest
from docs.domain.markdown_text import clean_markdown_text, extract_markdown_headings
from docs.domain.ports.evidence_repository import EvidenceRepository

_TRACEABILITY_PATH_KEYS = [
    ("manual_pdf", "institutional_pdf"),
    ("example_pdf", "structural_example_pdf"),
]
_EXCERPT_LENGTH = 1200


class EvidenceService:
    def __init__(self, repository: EvidenceRepository) -> None:
        self.repository = repository

    def build_rules(self, config: dict[str, Any]) -> Path:
        manual_dir = Path(config["paths"]["manual_dir"])
        extracted_dir = Path(config["paths"]["extracted_dir"])

        manual_files: list[ManualFileFact] = []
        for path in self.repository.list_manual_files(manual_dir):
            text = self.repository.read_text(path)
            manual_files.append(
                ManualFileFact(
                    path=path.resolve().as_posix(),
                    name=path.name,
                    sha256=self.repository.hash_file(path),
                    headings=extract_markdown_headings(text),
                    excerpt=clean_markdown_text(text[:_EXCERPT_LENGTH]),
                )
            )

        traceability: list[TraceabilityFact] = []
        for key, source_type in _TRACEABILITY_PATH_KEYS:
            path_str = config["paths"].get(key, "")
            # Legacy reads Path("").exists() when the key is absent/empty, which is
            # always False — skip the empty-string case directly rather than making
            # a pointless file_exists() call through the port.
            if not path_str:
                continue
            path = Path(path_str)
            if self.repository.file_exists(path):
                traceability.append(
                    TraceabilityFact(
                        path=path.resolve().as_posix(),
                        type=source_type,
                        sha256=self.repository.hash_file(path),
                        size=self.repository.file_size(path),
                    )
                )

        if self.repository.file_exists(extracted_dir):
            for path in self.repository.list_traceability_files(extracted_dir):
                traceability.append(
                    TraceabilityFact(
                        path=path.resolve().as_posix(),
                        type="extracted_traceability",
                        sha256=self.repository.hash_file(path),
                        size=self.repository.file_size(path),
                    )
                )

        section_contracts = config.get("section_contracts", {})
        contract_hashes = {
            section_id: self.repository.hash_json(contract)
            for section_id, contract in section_contracts.items()
        }

        strict_policy = config.get("strict_policy", {})
        manifest = build_manifest(
            manual_files=manual_files,
            traceability=traceability,
            advisor_overrides=config.get("advisor_overrides", []),
            draft_mode=strict_policy.get("draft", {}),
            strict_mode=strict_policy.get("strict", {}),
            preliminaries=config.get("preliminaries", {}),
            format=config.get("format", {}),
            apa7=config.get("apa7", {}),
            privacy=config.get("privacy", {}),
            section_contracts=section_contracts,
            contract_hashes=contract_hashes,
        )

        path = Path(config["paths"]["rules_manifest"])
        self.repository.write_manifest(path, manifest)
        return path
