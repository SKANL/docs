# src/docs/application/status.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.application.context import ContextService
from docs.application.ingest import _CLASSIFICATION_QUEUE_NAME, _DETECTION_REPORT_NAME
from docs.application.output_names import resolve_draft_docx_name
from docs.application.review import ReviewService
from docs.domain.document_status import DocumentStatus
from docs.domain.models.template import Template
from docs.domain.normative import NormativeSettings
from docs.domain.ports.document_repository import DocumentRepository
from docs.domain.ports.section_repository import SectionRepository

_FIGURE_CATALOG_NAME = "figure-catalog.json"


class StatusService:
    """`doc status` aggregator (design.md item I, ADR-I: aggregate-and-read,
    never persist). Reads already-produced artifacts -- context, sections,
    the ingest classification queue, the figure catalog, output -- through
    the SAME repositories/services the rest of the CLI already uses; no new
    state, no new source of truth."""

    def __init__(
        self,
        section_repository: SectionRepository,
        context_service: ContextService,
        review_service: ReviewService,
        document_repository: DocumentRepository,
    ) -> None:
        self.section_repository = section_repository
        self.context_service = context_service
        self.review_service = review_service
        self.document_repository = document_repository

    def status_summary(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        *,
        normative: NormativeSettings,
    ) -> DocumentStatus:
        context_statuses = self.context_service.status(doc_id, template)
        context_missing_topics = [status.id for status in context_statuses if status.missing]

        sections_missing: list[str] = []
        sections_scaffold: list[str] = []
        sections_needs_review: list[str] = []
        sections_authored = 0
        for section in sorted(template.sections, key=lambda item: item.order):
            if not self.section_repository.section_exists(doc_id, section.order, section.id):
                sections_missing.append(section.id)
                continue
            sections_authored += 1
            metadata, body = self.section_repository.read_section(doc_id, section.order, section.id)
            # Content-based, not `authored_by`-based: authored_by only
            # changes via the optional, explicit stamp-section command, so a
            # section can be fully authored (no leftover PENDIENTE) yet still
            # carry the default "harness-scaffold" value forever. Leftover
            # PENDIENTE markers are the real signal that a section still
            # needs authoring.
            #
            # Coverage note (holds for every real section kind): a contract
            # scaffold ALWAYS carries the disclaimer line
            # (`section_rendering.render_contract_scaffold`, "...resolver todos
            # los PENDIENTE...") until authored, so it is correctly flagged
            # regardless of whether it declares any `required_content`. The
            # only fresh scaffold with no PENDIENTE is a TOC section
            # (`render_toc_section` -> `[[TOC]]`), and that is correct: a TOC
            # is fully harness-generated and resolves at build time, so it
            # needs no authoring and must NOT be reported as pending.
            # ponytail: this couples "still-scaffold" to the disclaimer wording
            # carrying "PENDIENTE"; if that line ever drops the word, switch to
            # comparing `body` against a fresh scaffold render instead.
            if "PENDIENTE" in body:
                sections_scaffold.append(section.id)
            review = self.review_service.review_section(
                doc_id, template, section.id, strict=False, normative=normative
            )
            if review.issues:
                sections_needs_review.append(section.id)

        paths = config.get("paths", {})
        inbox_dir = Path(paths.get("inbox_dir", ""))
        sections_dir = Path(paths.get("sections_dir", ""))
        output_draft_dir = Path(paths.get("output_draft_dir", ""))
        output_final_dir = Path(paths.get("output_final_dir", ""))

        return DocumentStatus(
            doc_id=doc_id,
            context_filled=len(context_statuses) - len(context_missing_topics),
            context_total=len(context_statuses),
            context_missing_topics=context_missing_topics,
            sections_authored=sections_authored,
            sections_total=len(template.sections),
            sections_missing=sections_missing,
            sections_scaffold=sections_scaffold,
            sections_needs_review=sections_needs_review,
            ingest_ran=(inbox_dir / _DETECTION_REPORT_NAME).exists(),
            classification_pending=self._count_pending_classifications(inbox_dir),
            figures_count=self._count_figures(sections_dir),
            output_draft_exists=(output_draft_dir / resolve_draft_docx_name(doc_id, config)).exists(),
            output_final_exists=output_final_dir.is_dir() and any(output_final_dir.iterdir()),
            lifecycle=self.document_repository.read_document(doc_id).lifecycle,
            build_version=self._latest_build_version(paths),
        )

    def _latest_build_version(self, paths: dict[str, Any]) -> int | None:
        """Reads the highest `build_version` already logged under `runs/`
        (design.md item F) -- same artifact `PipelineService._next_build_version`
        writes to, read directly here rather than through a PipelineService
        dependency (StatusService stays aggregate-and-read only, ADR-I)."""
        runs_dir_value = paths.get("runs_dir")
        if not runs_dir_value:
            return None
        runs_dir = Path(runs_dir_value)
        if not runs_dir.exists():
            return None
        latest: int | None = None
        for path in runs_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            version = record.get("build_version")
            if isinstance(version, int) and (latest is None or version > latest):
                latest = version
        return latest

    def _count_pending_classifications(self, inbox_dir: Path) -> int:
        queue_path = inbox_dir / _CLASSIFICATION_QUEUE_NAME
        if not queue_path.exists():
            return 0
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        entries = data.get("entries", {})
        return sum(1 for entry in entries.values() if not entry.get("confirmed_role"))

    def _count_figures(self, sections_dir: Path) -> int:
        catalog_path = sections_dir / _FIGURE_CATALOG_NAME
        if not catalog_path.exists():
            return 0
        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        return len(data.get("figures", []))
