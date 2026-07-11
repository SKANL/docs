# src/docs/application/doctor.py
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.domain.doctor import Check, DoctorResult
from docs.domain.docx_structure import structure_parts
from docs.domain.models.template import Template
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.rules import review_rules


class DoctorService:
    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        asset_service: AssetService,
        tool_resolver: ToolResolverPort,
    ) -> None:
        self.evidence_repository = evidence_repository
        self.asset_service = asset_service
        self.tool_resolver = tool_resolver

    def run_doctor(self, doc_id: str, config: dict[str, Any], strict: bool = False) -> DoctorResult:
        checks: list[Check] = []

        for name in ["context_dir", "manual_dir"]:
            value = config["paths"].get(name)
            if value:
                path = Path(value)
                checks.append(Check(name, path.exists() and path.is_dir(), str(path)))

        if config["paths"].get("extracted_dir"):
            extracted = Path(config["paths"]["extracted_dir"])
            # De-hardcoded (verify follow-up NEW-SUGGESTION-1, sibling of PR1's
            # WARNING-2): was an unconditional comparison against a single
            # fixed expected policy string. Mirrors domain/rules.py's
            # _check_extracted_dir_policy exactly -- verifies a policy is
            # DECLARED (internal consistency), never a hardcoded expected value
            # (spec: document-pipeline "Extracted-dir policy checked only when
            # configured").
            extracted_dir_policy = config["paths"].get("extracted_dir_policy")
            checks.append(
                Check(
                    "extracted_dir_traceability_only",
                    bool(extracted_dir_policy) and isinstance(extracted_dir_policy, str),
                    f"{extracted} ({extracted_dir_policy or 'missing'})",
                    required=False,
                )
            )

        for name in ["template_docx", "example_pdf", "manual_pdf"]:
            value = config["paths"].get(name)
            if value:
                path = Path(value)
                checks.append(Check(name, path.exists() and path.is_file(), str(path), required=False))

        for part in structure_parts(config):
            if part.get("type") in {"cover_from_asset", "embed_docx"}:
                name = part.get("asset", "")
                path = self.asset_service.asset_path(doc_id, name)
                checks.append(
                    Check(
                        f"asset:{name}",
                        path.exists(),
                        str(path) if path.exists() else f"Falta el asset `{name}`. Agrégalo con `asset add`.",
                        required=False,
                    )
                )

        template = Template.model_validate(config)
        rules_path = Path(config["paths"]["rules_manifest"])
        manifest_exists = self.evidence_repository.file_exists(rules_path)
        manifest_size = self.evidence_repository.file_size(rules_path) if manifest_exists else 0
        rules_result = review_rules(template, manifest_exists, manifest_size, strict=False)
        checks.append(
            Check(
                "rules_config",
                rules_result.passed,
                "Contratos, APA 7 y preliminares configurados" if rules_result.passed else rules_result.to_markdown(),
                required=True,
            )
        )
        checks.append(
            Check("rules_manifest", manifest_exists, str(rules_path) if manifest_exists else "Ejecutar `build-rules`.", required=False)
        )

        checks.append(Check("python", True, sys.executable))
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
        checks.append(Check("pandoc", bool(pandoc), pandoc or "No encontrado en PATH. Instalar Pandoc para build-docx."))
        libreoffice = self.tool_resolver.resolve_libreoffice(config.get("paths", {}))
        # Optional, unlike pandoc: LibreOffice only renders the visual QA PDF.
        # Its absence must not fail-fast the whole pipeline and deny the user a
        # document the harness can otherwise build (qa-docx degrades in draft).
        checks.append(
            Check(
                "libreoffice",
                bool(libreoffice),
                libreoffice or "No encontrado en PATH. Instalar LibreOffice para el QA visual (opcional).",
                required=False,
            )
        )

        scripts_dir_value = config.get("paths", {}).get("documents_scripts_dir")
        scripts_dir = Path(scripts_dir_value) if scripts_dir_value else None
        for script in config.get("documents_tools", {}).get("scripts", []):
            script_path = scripts_dir / script if scripts_dir else None
            checks.append(
                Check(
                    f"documents_script:{script}",
                    script_path is not None and script_path.exists(),
                    str(script_path) if script_path is not None and script_path.exists() else "No encontrado en plugin Documents.",
                    required=strict and config.get("documents_tools", {}).get("required_in_strict", True),
                )
            )
        gh = shutil.which("gh")
        checks.append(Check("gh", bool(gh), gh or "No encontrado. Requerido para collect-issues.", required=strict))

        try:
            import docx  # noqa: F401

            checks.append(Check("python-docx", True, "Disponible"))
        except Exception as exc:
            checks.append(Check("python-docx", False, f"No disponible: {exc}"))

        return DoctorResult(checks)
