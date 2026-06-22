# src/docs/application/context_pack.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.markdown_text import keyword_set, matches_keywords
from docs.domain.models.template import SectionContract, Template
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository

_SECTION_PROMPT_NAMES = ["section-planner.md", "section-author.md", "section-reviewer.md"]
_APA_PROMPT_NAME = "apa7-citation-auditor.md"
_MAX_MANIFEST_FACTS = 40


class ContextPackService:
    def __init__(
        self,
        section_repository: SectionRepository,
        evidence_repository: EvidenceRepository,
        evidence_service: EvidenceService,
        review_service: ReviewService,
    ) -> None:
        self.section_repository = section_repository
        self.evidence_repository = evidence_repository
        self.evidence_service = evidence_service
        self.review_service = review_service

    def _read_prompt(self, prompts_dir: Path, name: str) -> str:
        path = prompts_dir / name
        if self.evidence_repository.file_exists(path):
            return self.evidence_repository.read_text(path).strip()
        return ""

    def pack_context(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        config: dict[str, Any],
        *,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        contract = template.section_contracts.get(section_id, SectionContract())
        required = contract.required_content
        apa_required = contract.apa_required
        keywords = keyword_set(section.title, section_id, " ".join(required))

        lines: list[str] = [
            f"# Context pack — {section.title}",
            "",
            "_Paquete generado por el arnés. Es el contexto curado para redactar esta sección. "
            "Redacta con `prompts/section-author.md`, luego corre `review-section "
            f"{section_id} --strict --json` y corrige hasta quedar en verde._",
            "",
            "## Contrato de sección",
            "",
            "```json",
            json.dumps(contract.model_dump(), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Checklist de contenido obligatorio",
            "",
        ]
        if required:
            lines.extend(f"- [ ] {item}" for item in required)
        else:
            lines.append("- (Sin `required_content` declarado.)")
        lines.extend(["", f"APA 7 requerido: {'sí' if apa_required else 'no'}.", ""])

        prompts_dir = Path(config["paths"]["prompts_dir"])
        prompt_names = list(_SECTION_PROMPT_NAMES)
        if apa_required:
            prompt_names.append(_APA_PROMPT_NAME)
        lines.extend(["## Prompts del rol", ""])
        for name in prompt_names:
            content = self._read_prompt(prompts_dir, name)
            if content:
                lines.extend([f"### {name}", "", content, ""])

        ledger_path = Path(config["paths"]["fact_ledger"])
        if self.evidence_repository.file_exists(ledger_path):
            ledger_text = self.evidence_repository.read_text(ledger_path)
            ledger_lines = [
                line.strip()
                for line in ledger_text.splitlines()
                if line.strip().startswith("- ") and matches_keywords(line, keywords)
            ]
            if ledger_lines:
                lines.extend(["## Hechos relevantes del ledger", ""])
                lines.extend(ledger_lines)
                lines.append("")

        manifest_facts = [
            fact
            for fact in self.evidence_service.load_manifest_facts(config)
            if matches_keywords(f"{fact.get('claim', '')} {fact.get('title', '')}", keywords)
        ]
        if manifest_facts:
            lines.extend(["## Evidencia relevante (manifests)", ""])
            for fact in manifest_facts[:_MAX_MANIFEST_FACTS]:
                claim = fact.get("claim") or fact.get("title") or ""
                classification = fact.get("classification", "")
                source = fact.get("source") or fact.get("url") or ""
                suffix = f" — {source}" if source else ""
                tag = f"[{classification}] " if classification else ""
                lines.append(f"- {tag}{claim}{suffix}")
            lines.append("")

        if self.section_repository.section_exists(doc_id, section.order, section.id):
            _metadata, body = self.section_repository.read_section(doc_id, section.order, section.id)
            review = self.review_service.review_section(
                doc_id,
                template,
                section_id,
                strict=False,
                excluded_terms=excluded_terms,
                is_policy_file=is_policy_file,
                first_person_patterns=first_person_patterns,
                subjective_terms=subjective_terms,
                secret_patterns=secret_patterns,
                scope_term=scope_term,
                scope_focus=scope_focus,
            )
            lines.extend(["## Borrador actual", "", "```markdown", body.strip(), "```", ""])
            lines.extend(["## Hallazgos actuales (review-section)", ""])
            if review.issues:
                for issue in review.issues:
                    code = f" ({issue.code})" if issue.code else ""
                    lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
            else:
                lines.append("- Sin hallazgos.")
            lines.append("")
        else:
            lines.extend(
                [
                    "## Borrador actual",
                    "",
                    f"_Aún no existe; ejecuta `build-section {section_id}` para generar el scaffold inicial._",
                    "",
                ]
            )

        out_path = self.section_repository.context_pack_path(doc_id, section.order, section.id)
        return self.section_repository.write_context_pack(out_path, "\n".join(lines))
