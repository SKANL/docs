# src/docs/application/context_pack.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.markdown_text import keyword_set, matches_keywords, strip_frontmatter_and_markdown
from docs.domain.models.template import SectionContract, Template
from docs.domain.normative import NormativeSettings
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository

_SECTION_PROMPT_NAMES = ["section-planner.md", "section-author.md", "section-reviewer.md"]
_APA_PROMPT_NAME = "apa7-citation-auditor.md"
_DOCUMENT_PROMPT_NAMES = ["document-reviewer.md", "docx-builder.md", "format-auditor.md"]
_MAX_MANIFEST_FACTS = 40
_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b")


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
            normative = NormativeSettings(
                excluded_terms=excluded_terms,
                is_policy_file=is_policy_file,
                first_person_patterns=first_person_patterns,
                subjective_terms=subjective_terms,
                secret_patterns=secret_patterns,
                scope_term=scope_term,
                scope_focus=scope_focus,
            )
            review = self.review_service.review_section(doc_id, template, section_id, strict=False, normative=normative)
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

    def pack_context_document(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        *,
        manifest_exists: bool,
        manifest_size: int,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> Path:
        lines: list[str] = [
            "# Context pack — DOCUMENTO COMPLETO",
            "",
            "_Paquete para la revisión global y el cierre del documento. Úsalo con el rol "
            "`document-reviewer.md` y corre `review-document --strict --json` y `verify --strict` "
            "hasta quedar en verde._",
            "",
            "## Estado por sección",
            "",
            "| Sección | Existe | Palabras | PENDIENTE | Autor | Modelo |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for section in sorted(template.sections, key=lambda item: item.order):
            if not self.section_repository.section_exists(doc_id, section.order, section.id):
                lines.append(f"| {section.id} | no | – | – | – | – |")
                continue
            metadata, body = self.section_repository.read_section(doc_id, section.order, section.id)
            section_path = self.section_repository.section_path(doc_id, section.order, section.id)
            raw = section_path.read_text(encoding="utf-8")
            words = len(_WORD_RE.findall(strip_frontmatter_and_markdown(raw)))
            pending = "sí" if "PENDIENTE" in body else "no"
            author = metadata.get("authored_by", "–")
            model = metadata.get("model", "–")
            lines.append(f"| {section.id} | sí | {words} | {pending} | {author} | {model} |")
        lines.append("")

        prompts_dir = Path(config["paths"]["prompts_dir"])
        lines.extend(["## Prompts del rol", ""])
        for name in _DOCUMENT_PROMPT_NAMES:
            content = self._read_prompt(prompts_dir, name)
            if content:
                lines.extend([f"### {name}", "", content, ""])

        normative = NormativeSettings(
            excluded_terms=excluded_terms,
            is_policy_file=is_policy_file,
            first_person_patterns=first_person_patterns,
            subjective_terms=subjective_terms,
            secret_patterns=secret_patterns,
            scope_term=scope_term,
            scope_focus=scope_focus,
        )
        review = self.review_service.review_document(
            doc_id, template, strict=False, manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )
        lines.extend(["## Hallazgos globales (review-document)", ""])
        if review.issues:
            for issue in review.issues:
                code = f" ({issue.code})" if issue.code else ""
                lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
        else:
            lines.append("- Sin hallazgos.")
        lines.append("")

        ledger_path = Path(config["paths"]["fact_ledger"])
        if self.evidence_repository.file_exists(ledger_path):
            ledger_text = self.evidence_repository.read_text(ledger_path)
            lines.extend(
                [
                    "## Hechos canónicos (ledger)",
                    "",
                    f"Fuente de verdad: `{ledger_path.resolve().as_posix()}`. Toda afirmación del documento "
                    "debe ser consistente con estos hechos.",
                    "",
                    ledger_text.strip(),
                    "",
                ]
            )

        out_path = self.section_repository.document_context_pack_path(doc_id)
        return self.section_repository.write_context_pack(out_path, "\n".join(lines))
