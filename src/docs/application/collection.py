# src/docs/application/collection.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docs.domain.collection import classify_source, dedupe_facts, extract_github_repo, parse_gh_issues
from docs.domain.markdown_text import clean_markdown_text
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository

_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
_SOURCE_EXCERPT_LENGTH = 900
_CODE_EXCERPT_LENGTH = 900


class CollectionService:
    def __init__(self, source_repository: SourceRepository, evidence_repository: EvidenceRepository) -> None:
        self.source_repository = source_repository
        self.evidence_repository = evidence_repository

    def collect_sources(self, config: dict[str, Any]) -> Path:
        manifest_path = Path(config["paths"]["source_manifest"])
        sources: list[dict[str, Any]] = []

        def add_file(path: Path, source_type: str, use: str) -> None:
            if not path.exists() or not path.is_file():
                return
            text = ""
            if path.suffix.lower() in _TEXT_SUFFIXES:
                text = self.evidence_repository.read_text(path)
            sources.append(
                {
                    "path": path.resolve().as_posix(),
                    "type": source_type,
                    "use": use,
                    "classification": classify_source(source_type),
                    "sha256": self.evidence_repository.hash_file(path),
                    "excerpt": clean_markdown_text(text[:_SOURCE_EXCERPT_LENGTH]) if text else "",
                }
            )

        context_dir = Path(config["paths"]["context_dir"])
        for path in self.source_repository.glob_markdown(context_dir):
            if path.name.startswith("_") or path.name == "index.md":
                continue
            add_file(path, "approved_context", "contexto aprobado del documento")

        manual_dir = config["paths"].get("manual_dir")
        if manual_dir and Path(manual_dir).exists():
            for path in self.source_repository.glob_markdown(Path(manual_dir)):
                add_file(path, "institutional_manual", "norma documental obligatoria")

        evidence = config.get("evidence_sources", {})
        evidence_root = Path(evidence["root"]) if evidence.get("root") else None
        for entry in evidence.get("files", []):
            rel = entry.get("path", "")
            target = (evidence_root / rel) if evidence_root else Path(rel)
            add_file(target, entry.get("type", "evidence"), entry.get("use", "evidencia técnica secundaria"))

        if config["paths"].get("template_docx"):
            add_file(
                Path(config["paths"]["template_docx"]), "cover_template", "plantilla de portada reutilizable"
            )
        if config["paths"].get("example_pdf"):
            add_file(
                Path(config["paths"]["example_pdf"]),
                "example_reference",
                "referencia estructural, no fuente de contenido",
            )

        # Legacy calls load_context(config) twice (once per check below) for the
        # identical result. read_context_texts is referentially transparent over
        # the same config, so this service computes it once and reuses it —
        # not a behavior change, just removing a verbatim duplicate call.
        context_texts = self.source_repository.read_context_texts(context_dir)
        context_text = "\n".join(context_texts.values()).lower()

        facts: list[dict[str, Any]] = list(config.get("collect_facts_seed", []))
        contradiction_terms = [term.lower() for term in evidence.get("scope_contradiction_terms", [])]
        if contradiction_terms and any(term in context_text for term in contradiction_terms):
            facts.append(
                {
                    "classification": "contradiccion",
                    "claim": (
                        "El contexto menciona términos fuera del alcance declarado; "
                        "resolver con evidencia o delimitar."
                    ),
                    "source": "context",
                }
            )

        for field in config.get("privacy", {}).get("sensitive_context_fields", []):
            if re.search(
                rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|",
                "\n".join(context_texts.values()),
                flags=re.IGNORECASE,
            ):
                facts.append(
                    {
                        "classification": "dato_sensible",
                        "claim": (
                            f"El contexto aprobado contiene el campo sensible `{field}`; "
                            "no debe pasar al cuerpo sin instrucción explícita."
                        ),
                        "source": "context",
                    }
                )

        manifest = {
            "schema": 1,
            "policy": config.get("project", {}).get("scope_policy", ""),
            "source_count": len(sources),
            "sources": sources,
            "facts": facts,
        }
        self.evidence_repository.write_manifest(manifest_path, manifest)
        return manifest_path

    def collect_issues(self, config: dict[str, Any], repo_root: Path) -> Path:
        gh = self.source_repository.find_executable("gh")
        if not gh:
            raise RuntimeError("GitHub CLI `gh` no está disponible. Instálalo o exporta issues a JSON.")
        remote = self.source_repository.detect_github_remote(repo_root)
        repo = extract_github_repo(remote)
        if not repo:
            raise RuntimeError("No se pudo detectar el repositorio GitHub desde `git remote get-url origin`.")
        raw = self.source_repository.run_gh_issue_list(gh, repo)
        issues = parse_gh_issues(raw)
        manifest_path = Path(config["paths"]["issues_manifest"])
        payload = {"schema": 1, "repo": repo, "issue_count": len(issues), "issues": issues}
        self.evidence_repository.write_manifest(manifest_path, payload)
        return manifest_path

    def collect_code_evidence(self, config: dict[str, Any], repo_root: Path) -> Path:
        manifest_path = Path(config["paths"]["code_evidence_manifest"])
        evidence = config.get("evidence_sources", {})
        root = Path(evidence["root"]) if evidence.get("root") else None
        files: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []

        def resolve(rel: str) -> Path:
            return (root / rel) if root else Path(rel)

        def add_code_file(path: Path, evidence_type: str) -> str:
            if not path.exists() or not path.is_file():
                return ""
            text = self.evidence_repository.read_text(path)
            files.append(
                {
                    "path": path.resolve().as_posix(),
                    "type": evidence_type,
                    "sha256": self.evidence_repository.hash_file(path),
                    "excerpt": clean_markdown_text(text[:_CODE_EXCERPT_LENGTH]),
                }
            )
            return text

        dependency_manifest = ""
        for entry in evidence.get("files", []):
            text = add_code_file(resolve(entry.get("path", "")), entry.get("type", "evidence"))
            if entry.get("type", "").endswith("dependency_manifest"):
                dependency_manifest = text

        for dependency in evidence.get("dependency_tokens", []):
            if dependency.lower() in dependency_manifest.lower():
                facts.append(
                    {
                        "classification": "confirmado",
                        "claim": f"El proyecto declara la dependencia `{dependency}`.",
                        "source": "dependency_manifest",
                    }
                )

        source_tokens = evidence.get("source_tokens", [])
        for glob_entry in evidence.get("code_globs", []):
            if not root:
                break
            limit = int(glob_entry.get("limit", 120))
            matched = self.source_repository.glob_pattern(root, glob_entry.get("glob", ""))
            for path in matched[:limit]:
                if not path.is_file():
                    continue
                text = add_code_file(path, glob_entry.get("type", "source"))
                lowered = text.lower()
                for token_entry in source_tokens:
                    token = token_entry.get("token", "").lower()
                    if token and token in lowered:
                        facts.append(
                            {
                                "classification": "confirmado",
                                "claim": f"Se detectó uso de {token_entry.get('label', token)} en el código.",
                                "source": path.resolve().as_posix(),
                            }
                        )
                        break

        if root and evidence.get("git_log", False):
            facts.extend(self._collect_git_facts(root, repo_root))

        manifest = {
            "schema": 1,
            "root": root.resolve().as_posix() if root else "",
            "file_count": len(files),
            "files": files,
            "facts": dedupe_facts(facts),
        }
        self.evidence_repository.write_manifest(manifest_path, manifest)
        return manifest_path

    def _collect_git_facts(self, path: Path, repo_root: Path) -> list[dict[str, Any]]:
        stdout = self.source_repository.run_git_log(path, repo_root)
        if stdout is None:
            return [
                {
                    "classification": "pendiente",
                    "claim": "No se pudo obtener git log para la app móvil.",
                    "source": "git",
                }
            ]
        facts: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            if line.strip():
                facts.append(
                    {
                        "classification": "confirmado",
                        "claim": f"Commit relacionado con app móvil: {line.strip()}",
                        "source": "git log",
                    }
                )
        return facts
