# src/docs/application/revision.py
"""RevisionService (design.md item B, spec: document-revise): the harness
provides diff/scoped-re-validation/provenance mechanics; the agent supplies
the actual replacement text (`new_body`/`new_value`) out-of-band. No
embedded LLM -- mirrors `CorrectionsService`'s read-modify-write provenance
style (`application/corrections.py`), reuses `ReviewService.review_section`/
`review_document`, `ContextService.set`/`show`, and the `apply_stamp`/
`with_frontmatter` primitives `ReviewService.stamp_section` is built from."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.application.context import ContextService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.normative import NormativeSettings
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository
from docs.domain.revision import RevisionResult, summarize_change, unified_diff
from docs.domain.sections import apply_stamp, with_frontmatter

_STRUCTURAL_SCOPE_ERROR = (
    "`{target_id}` no es una sección ni un tema de contexto conocido de esta "
    "plantilla. `revise` no admite cambios estructurales (agregar/quitar "
    "secciones o re-ingesta de fuentes); usa los flujos de autoría/ingesta "
    "existentes para eso."
)


class RevisionService:
    def __init__(
        self,
        section_repository: SectionRepository,
        review_service: ReviewService,
        context_service: ContextService,
        evidence_repository: EvidenceRepository,
    ) -> None:
        self.section_repository = section_repository
        self.review_service = review_service
        self.context_service = context_service
        self.evidence_repository = evidence_repository

    def resolve_target(self, template: Template, target_id: str) -> str:
        """Classifies `target_id` as `"section"` or `"topic"` for CLI
        dispatch (spec: document-revise "Revise Scope Boundary" -- an id
        matching neither is a structural request, out of `revise`'s scope)."""
        if any(section.id == target_id for section in template.sections):
            return "section"
        if any(topic.id == target_id for topic in template.context_schema.topics):
            return "topic"
        raise ValueError(_STRUCTURAL_SCOPE_ERROR.format(target_id=target_id))

    def revise(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        section_id: str,
        new_body: str,
        request: str,
        *,
        strict: bool = False,
        manifest_exists: bool = False,
        manifest_size: int = 0,
        normative: NormativeSettings,
        now: str,
    ) -> RevisionResult:
        section = next((s for s in template.sections if s.id == section_id), None)
        if section is None:
            raise ValueError(_STRUCTURAL_SCOPE_ERROR.format(target_id=section_id))

        metadata, before = self.section_repository.read_section(doc_id, section.order, section.id)
        after = new_body
        diff = unified_diff(before, after, label=section.id)
        summary = summarize_change(before, after)

        after_hash = self.evidence_repository.hash_text(after)
        new_metadata = apply_stamp(
            metadata, section.id, section.title, after, after_hash,
            metadata.get("authored_by", "revise"), metadata.get("model", ""), now,
        )
        self.section_repository.write_section(
            doc_id, section.order, section.id, with_frontmatter(after, new_metadata)
        )

        # Scoped re-validation (spec: "Scoped Re-Validation") -- ONLY the
        # edited section + review-document, never the other sections.
        self.review_service.review_section(doc_id, template, section.id, strict=strict, normative=normative)
        self.review_service.review_document(
            doc_id, template, strict=strict,
            manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )

        before_hash = self.evidence_repository.hash_text(before)
        diff_path = self._write_diff(config, f"{section.order:03d}-{section.id}", diff)
        self._append_log_entry(
            config, request=request, target_id=section.id, diff_path=diff_path,
            before_hash=before_hash, after_hash=after_hash, ripple=[], ts=now,
        )

        return RevisionResult(
            target_id=section.id, before=before, after=after, diff=diff,
            summary=summary, changed_sections=[section.id], diff_path=diff_path,
        )

    def revise_topic(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        topic_id: str,
        new_value: str,
        request: str,
        *,
        field: str = "",
        strict: bool = False,
        manifest_exists: bool = False,
        manifest_size: int = 0,
        normative: NormativeSettings,
        now: str,
    ) -> RevisionResult:
        topic = next((t for t in template.context_schema.topics if t.id == topic_id), None)
        if topic is None:
            raise ValueError(_STRUCTURAL_SCOPE_ERROR.format(target_id=topic_id))

        before = self._show_topic_or_blank(doc_id, topic_id)
        self.context_service.set(doc_id, template, topic_id, new_value, field=field)
        after = self._show_topic_or_blank(doc_id, topic_id)

        diff = unified_diff(before, after, label=topic_id)
        summary = summarize_change(before, after)

        # Context-topic ripple (spec: "Context-topic edit ripples to
        # dependent sections") -- `Topic.consumed_by` already IS the
        # section-consumption mapping (template.py:20); no separate lookup
        # needed. Sections NOT in `consumed_by` are never re-validated.
        known_section_ids = {section.id for section in template.sections}
        dependent_sections = [sid for sid in topic.consumed_by if sid in known_section_ids]
        for section_id in dependent_sections:
            self.review_service.review_section(doc_id, template, section_id, strict=strict, normative=normative)
        self.review_service.review_document(
            doc_id, template, strict=strict,
            manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )

        before_hash = self.evidence_repository.hash_text(before)
        after_hash = self.evidence_repository.hash_text(after)
        diff_path = self._write_diff(config, f"topic-{topic_id}", diff)
        self._append_log_entry(
            config, request=request, target_id=topic_id, diff_path=diff_path,
            before_hash=before_hash, after_hash=after_hash, ripple=dependent_sections, ts=now,
        )

        return RevisionResult(
            target_id=topic_id, before=before, after=after, diff=diff,
            summary=summary, changed_sections=dependent_sections, diff_path=diff_path,
        )

    def _show_topic_or_blank(self, doc_id: str, topic_id: str) -> str:
        try:
            return self.context_service.show(doc_id, topic_id)
        except FileNotFoundError:
            return ""

    # ── provenance (revision-log.json + per-revision .diff snapshot) ────
    # Mirrors CorrectionsService.apply_corrections's read-modify-write
    # append style (application/corrections.py) -- reused, not reinvented.

    def _revisions_dir(self, config: dict[str, Any]) -> Path:
        path = Path(config["paths"]["sections_dir"]) / "_revisions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_diff(self, config: dict[str, Any], prefix: str, diff: str) -> str:
        revisions_dir = self._revisions_dir(config)
        n = len(list(revisions_dir.glob(f"{prefix}.*.diff"))) + 1
        path = revisions_dir / f"{prefix}.{n}.diff"
        path.write_text(diff, encoding="utf-8")
        return str(path)

    def _append_log_entry(
        self, config: dict[str, Any], *, request: str, target_id: str, diff_path: str,
        before_hash: str, after_hash: str, ripple: list[str], ts: str,
    ) -> None:
        log_path = self._revisions_dir(config) / "revision-log.json"
        state: dict[str, Any] = (
            json.loads(log_path.read_text(encoding="utf-8"))
            if log_path.exists()
            else {"schema": 1, "entries": []}
        )
        state.setdefault("entries", []).append(
            {
                "request": request,
                "section_id": target_id,
                "diff_path": diff_path,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "ripple": ripple,
                "ts": ts,
            }
        )
        log_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
