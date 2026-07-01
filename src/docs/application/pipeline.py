# src/docs/application/pipeline.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docs.application.collection import CollectionService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository
from docs.domain.workspace import Workspace

_DRAFT_DOCX_NAME = "tesina-draft.docx"


class PipelineService:
    def __init__(
        self,
        doctor_service: DoctorService,
        evidence_service: EvidenceService,
        evidence_repository: EvidenceRepository,
        collection_service: CollectionService,
        source_repository: SourceRepository,
        review_service: ReviewService,
        context_pack_service: ContextPackService,
        context_repository: ContextRepository,
        docx_assembly_service: DocxAssemblyService,
        format_audit_service: FormatAuditService,
        qa_service: QaService,
        workspace: Workspace,
    ) -> None:
        self.doctor_service = doctor_service
        self.evidence_service = evidence_service
        self.evidence_repository = evidence_repository
        self.collection_service = collection_service
        self.source_repository = source_repository
        self.review_service = review_service
        self.context_pack_service = context_pack_service
        self.context_repository = context_repository
        self.docx_assembly_service = docx_assembly_service
        self.format_audit_service = format_audit_service
        self.qa_service = qa_service
        self.workspace = workspace

    def log_run(
        self, doc_id: str, config: dict[str, Any], repo_root: Path, command: str, payload: dict[str, Any]
    ) -> Path:
        runs_dir = self._runs_dir(doc_id, config)
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="microseconds")
        record = {
            "timestamp": timestamp,
            "command": command,
            "git_commit": self.source_repository.run_git_rev_parse_head(repo_root),
            **payload,
        }
        safe_name = timestamp.replace(":", "-")
        path = runs_dir / f"{safe_name}-{command}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def list_runs(self, doc_id: str, config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        runs_dir = self._runs_dir(doc_id, config)
        if not runs_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return records

    def _runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
        return self.workspace.doc_root(doc_id) / "runs"
