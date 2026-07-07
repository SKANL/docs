# src/docs/domain/evidence.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManualFileFact:
    path: str
    name: str
    sha256: str
    headings: list[str]
    excerpt: str


@dataclass(frozen=True)
class TraceabilityFact:
    path: str
    type: str
    sha256: str
    size: int


def build_manifest(
    manual_files: list[ManualFileFact],
    traceability: list[TraceabilityFact],
    advisor_overrides: list[dict],
    draft_mode: dict,
    strict_mode: dict,
    preliminaries: dict,
    format: dict,
    apa7: dict,
    privacy: dict,
    section_contracts: dict[str, dict],
    contract_hashes: dict[str, str],
    normative_source: str = "",
    skipped_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": 1,
        "policy": {
            # Template-declared, never a hardcoded document-type literal (spec:
            # document-template "No hardcoded document-type literal in domain
            # code"; evidence.py #7). Default "" when the template declares none.
            "normative_source": normative_source,
            "pdf_and_extracted_use": "rules_traceability_only",
            "apa_style": "APA 7",
            # Legacy quirk (intentional, not a bug): advisor_overrides is duplicated
            # both here and at the manifest's top level (see below). Preserve as-is.
            "advisor_overrides": advisor_overrides,
            "draft_mode": draft_mode,
            "strict_mode": strict_mode,
        },
        "manual_files": [
            {
                "path": fact.path,
                "name": fact.name,
                "sha256": fact.sha256,
                "headings": fact.headings,
                "excerpt": fact.excerpt,
            }
            for fact in manual_files
        ],
        "traceability": [
            {"path": fact.path, "type": fact.type, "sha256": fact.sha256, "size": fact.size}
            for fact in traceability
        ],
        "preliminaries": preliminaries,
        "format": format,
        "advisor_overrides": advisor_overrides,
        "apa7": apa7,
        "privacy": privacy,
        "section_contracts": section_contracts,
        "contract_hashes": contract_hashes,
        # Optional template-declared paths (`manual_dir`/`extracted_dir`) that
        # were absent from `paths` config this run -- reported, never silently
        # dropped and never a hard failure (spec: document-pipeline "Build-Rules
        # Guards Absent Paths").
        "skipped_paths": skipped_paths or [],
    }


@dataclass(frozen=True)
class ManualHashFact:
    path: str
    sha256: str


def build_rules_hash_payload(
    manual_files: list[ManualHashFact],
    section_contracts: dict[str, dict],
    format: dict,
    apa7: dict,
    structure: list[dict],
    preliminaries: dict,
) -> dict[str, Any]:
    return {
        "manual_dir": [{"path": fact.path, "sha256": fact.sha256} for fact in manual_files],
        "section_contracts": section_contracts,
        "format": format,
        "apa7": apa7,
        "structure": structure,
        "preliminaries": preliminaries,
    }


@dataclass(frozen=True)
class SourceHashFileFact:
    path: str
    sha256: str


def build_source_hash_payload(
    files: list[SourceHashFileFact], config_sections: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [{"path": fact.path, "sha256": fact.sha256} for fact in files]
    payload.append({"config_sections": config_sections})
    return payload


@dataclass(frozen=True)
class PromptHashFileFact:
    name: str
    sha256: str


def build_prompt_hash_payload(files: list[PromptHashFileFact]) -> list[dict[str, str]]:
    # Legacy quirk (intentional, verbatim from the original single-file harness
    # script, lines 433-439): the dict key is "path" but the value is the bare
    # filename (path.name), not a full path — prompts are hashed by filename
    # only, unlike source_hash's files.
    return [{"path": fact.name, "sha256": fact.sha256} for fact in files]
