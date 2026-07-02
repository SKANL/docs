# src/docs/cli/_shared.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.application.context_pack import ContextPackService
from docs.application.corrections import CorrectionsService
from docs.application.doctor import DoctorService
from docs.application.documents import DocumentService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@dataclass(frozen=True)
class ResolvedContext:
    doc_id: str
    config: dict[str, Any]
    template: Template


def build_workspace() -> Workspace:
    """Workspace roots from env (injectable in tests), cwd-relative defaults.
    Legacy hardcoded HARNESS_ROOT/documents & templates; no library equivalent
    (Judgment call 2)."""
    documents_dir = Path(os.environ.get("DOCS_DOCUMENTS_DIR", "documents"))
    templates_dir = Path(os.environ.get("DOCS_TEMPLATES_DIR", "templates"))
    return Workspace(documents_dir=documents_dir, templates_dir=templates_dir)


class Deps:
    """Composition root — builds every adapter + service exactly as the
    integration-test _service() helpers do, plus config assembly."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace or build_workspace()
        document_repo = JsonDocumentRepository(self.workspace)
        evidence_repo = JsonEvidenceRepository()
        section_repo = JsonSectionRepository(self.workspace)
        source_repo = FilesystemSourceRepository()
        context_repo = JsonContextRepository(self.workspace)
        self.document_repository = document_repo
        self.context_repository = context_repo
        self.source_repository = source_repo

        asset_service = AssetService(FilesystemAssetRepository(), self.workspace)
        evidence_service = EvidenceService(evidence_repo)
        review_service = ReviewService(section_repo)
        collection_service = CollectionService(source_repo, evidence_repo)
        context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
        tool_resolver = SystemToolResolverAdapter()
        docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
        format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
        qa_service = QaService(LibreOfficeQaAdapter(), format_audit_service)
        doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)

        self.assets = asset_service
        self.evidence = evidence_service
        self.review = review_service
        self.collection = collection_service
        self.context_pack = context_pack_service
        self.docx = docx_assembly_service
        self.format_audit = format_audit_service
        self.qa = qa_service
        self.doctor = doctor_service
        self.documents = DocumentService(document_repo)
        self.corrections = CorrectionsService(section_repo, evidence_repo)
        self.context = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
        self.pipeline = PipelineService(
            doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
            review_service, context_pack_service, context_repo, docx_assembly_service,
            format_audit_service, qa_service, self.workspace,
        )

    # ── config assembly (migrated resolve_config / load_document) ──────────
    def resolve_context(self, doc: str = "") -> ResolvedContext:
        doc_id = doc or self.document_repository.active_id()
        if not doc_id:
            raise RuntimeError("No hay documento activo. Usa `doc new <id>` o `doc use <id>`.")
        document = self.document_repository.read_document(doc_id)      # Document (extra allowed)
        template = self.document_repository.load_template(document.template)
        merged = _deep_merge(template.model_dump(), document.model_dump())
        merged = _expand_tokens(merged, _standard_tokens(self.workspace))
        paths = dict(merged.get("paths", {}))
        paths.update(_computed_paths(self.workspace.doc_root(doc_id)))
        # prompts_dir: per-document default, template/document override wins if set
        paths.setdefault("prompts_dir", str(self.workspace.doc_root(doc_id) / "prompts"))
        merged["paths"] = paths
        merged["doc_id"] = doc_id
        return ResolvedContext(doc_id=doc_id, config=merged, template=Template.model_validate(merged))


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def _expand_tokens(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _expand_tokens(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_tokens(v, tokens) for v in value]
    if isinstance(value, str):
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
    return value


def _standard_tokens(workspace: Workspace) -> dict[str, str]:
    # Harness-global tokens have no library equivalent (Judgment call 2);
    # expand only what the workspace/cwd can supply. Unresolved tokens stay literal.
    return {
        "{templates_dir}": str(workspace.templates_dir.resolve()),
        "{documents_dir}": str(workspace.documents_dir.resolve()),
        "{cwd}": str(Path.cwd().resolve()),
    }


def _computed_paths(doc_root: Path) -> dict[str, str]:
    sections = doc_root / "sections"
    context = doc_root / "context"
    corrections = doc_root / "corrections"
    output = doc_root / "output"
    return {
        "context_dir": str(context),
        "context_index": str(context / "index.json"),
        "context_requests": str(context / "_requests.md"),
        "assets_dir": str(doc_root / "assets"),
        "sections_dir": str(sections),
        "source_manifest": str(sections / "source-manifest.json"),
        "issues_manifest": str(sections / "issues-manifest.json"),
        "code_evidence_manifest": str(sections / "code-evidence-manifest.json"),
        "rules_manifest": str(sections / "manual-rules.json"),
        "fact_ledger": str(sections / "00-fact-ledger.md"),
        "corrections_inbox_dir": str(corrections / "inbox"),
        "corrections_applied": str(corrections / "applied.json"),
        "output_draft_dir": str(output / "draft"),
        "output_final_dir": str(output / "final"),
        "output_qa_dir": str(output / "qa"),
        "runs_dir": str(doc_root / "runs"),
    }


def emit_result(result: Any, as_json: bool) -> None:
    """Migrated _emit_result (3152-3157). Prints to stdout."""
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
