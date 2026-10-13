"""HTTP handlers for the specialist document tools.

Thin adapters over the services the CLI calls (collection, evidence rules and
ledger, DOCX build and format audit, PDF translation, doctor, issue-code
catalogue).  HTTP never takes a filesystem path of its own: outputs and
repository roots are confined to the workspace, sources are workspace artifact
ids or capped uploads, and responses carry workspace-relative paths only.
A tool that cannot run (missing `gh`, no pandoc, no PDF adapters) answers with
a structured degraded result rather than a server error.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from uuid import uuid4

from docs.application.document_tools import check_rules, run_diagnostics, write_fact_ledger
from docs.application.imports import ImportError, SourceImportService
from docs.application.templates import TemplateService, builtin_names
from docs.application.translate import UntranslatablePdfError
from docs.domain.issue_codes import ISSUE_CODE_FAMILIES, ISSUE_CODES
from docs.domain.tool_capability import ToolUnavailableError
from docs.domain.translation_sidecars import translation_sidecars

from . import authoring_dto as dto
from .authoring_routes import RouteSupport, _import_error
from .http import APIError, Request, Response
from .quality_routes import QualityRoutes

_LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")
# Checks that probe an external tool or optional library: when they fail the capability is
# *unavailable*, not the workspace broken.
_TOOLCHAIN = frozenset({
    "pandoc", "libreoffice", "gh", "java", "mmdc", "resvg", "pdf_page_render", "pdf_raster_extract", "python-docx",
})
# ponytail: scraped from the detail line of `pandoc`; expose a typed version when more tools need one
_TRAILING_VERSION = re.compile(r"\((\d+(?:\.\d+)+)\)\s*$")
_TRANSLATIONS = Path("artifacts") / "translations"


def _status(name: str, ok: bool, required: bool) -> Literal["ok", "warn", "error", "unavailable"]:
    if ok:
        return "ok"
    if name in _TOOLCHAIN:
        return "unavailable"
    return "error" if required else "warn"


class ToolRoutes(RouteSupport):
    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
        quality: QualityRoutes,
        import_service: SourceImportService,
    ) -> None:
        super().__init__(workspace_root=workspace_root, services_for=services_for)
        self._quality = quality
        self._import = import_service

    # -- shared --------------------------------------------------------------
    @staticmethod
    def _clean(message: str, root: Path) -> str:
        return message.replace(str(root), ".")

    @staticmethod
    def _rel(root: Path, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise APIError("path_outside_workspace", "The tool wrote outside the workspace", 409) from exc

    @staticmethod
    def _confined(base: Path, requested: str, suffix: str) -> Path:
        """A path strictly inside `base` with the expected extension; anything else is refused."""
        parts = PureWindowsPath(requested)  # parses both `/` and `\` separators
        message = f"Output must be a relative {suffix} path inside the workspace"
        if not requested.strip() or parts.anchor or parts.drive or ".." in parts.parts or Path(requested).is_absolute():
            raise APIError("output_not_permitted", message, 400)
        candidate = (base / requested).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise APIError("output_not_permitted", message, 400) from exc
        if candidate.suffix.lower() != suffix:
            raise APIError("output_not_permitted", message, 400)
        return candidate

    def _document(self, request: Request, document_id: str, body_workspace: str | None) -> tuple[Path, Any, Any]:
        root, deps = self._open(request, document_id, body_workspace)
        return Path(root).resolve(), deps, self._resolve(deps, document_id)

    @staticmethod
    def _repo_root(root: Path, config: dict[str, Any], requested: str | None) -> Path:
        """The workspace, or the evidence root the document itself declares; never a client-chosen path."""
        evidence = (config.get("evidence_sources") or {}).get("root")
        configured = (root / evidence).resolve() if evidence else None
        if requested is None:
            return configured or root
        candidate = Path(requested)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if resolved not in {root, configured}:
            raise APIError(
                "repo_root_not_permitted", "repo_root must be the workspace or the configured evidence root", 400,
            )
        return resolved

    def _file_tool(
        self, request: Request, document_id: str, run: Callable[[Any, Any, Path], Path], *, repo: bool = False,
    ) -> Response:
        data = (
            self._body(request, dto.CollectRepoRequest) if repo else self._body(request, dto.WorkspaceScopedRequest)
        )
        root, deps, resolved = self._document(request, document_id, data.workspace_id)
        requested = data.repo_root if isinstance(data, dto.CollectRepoRequest) else None
        repo_root = self._repo_root(root, resolved.config, requested) if repo else root
        try:
            written = run(deps, resolved, repo_root)
        except ToolUnavailableError as exc:  # a missing tool or remote, not a server fault
            return Response.json(dto.ToolFileResponse(
                document_id=document_id, path=None, degraded=True, message=self._clean(str(exc), root),
            ).model_dump())
        except (KeyError, ValueError, OSError) as exc:
            raise APIError("tool_failed", self._clean(str(exc), root), 422) from exc
        return Response.json(dto.ToolFileResponse(document_id=document_id, path=self._rel(root, written)).model_dump())

    # -- collection / rules / ledger ----------------------------------------
    def collect_sources(self, request: Request, document_id: str) -> Response:
        return self._file_tool(
            request, document_id, lambda deps, resolved, _: deps.collection.collect_sources(resolved.config),
        )

    def collect_issues(self, request: Request, document_id: str) -> Response:
        return self._file_tool(
            request, document_id,
            lambda deps, resolved, repo_root: deps.collection.collect_issues(resolved.config, repo_root), repo=True,
        )

    def collect_code_evidence(self, request: Request, document_id: str) -> Response:
        return self._file_tool(
            request, document_id,
            lambda deps, resolved, repo_root: deps.collection.collect_code_evidence(resolved.config, repo_root),
            repo=True,
        )

    def build_rules(self, request: Request, document_id: str) -> Response:
        return self._file_tool(
            request, document_id, lambda deps, resolved, _: deps.evidence.build_rules(resolved.config),
        )

    def build_ledger(self, request: Request, document_id: str) -> Response:
        return self._file_tool(request, document_id, lambda deps, resolved, _: write_fact_ledger(deps, resolved))

    def review_rules(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.RulesReviewRequest)
        _, deps, resolved = self._document(request, document_id, data.workspace_id)
        result = check_rules(deps, resolved, strict=data.strict)
        return Response.json(dto.RulesReviewResponse(
            document_id=document_id, strict=data.strict, passed=result.passed,
            issues=[issue.to_dict() for issue in result.issues],
        ).model_dump())

    # -- DOCX ------------------------------------------------------------------
    def build_docx(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.DocxBuildRequest)
        root, deps, resolved = self._document(request, document_id, data.workspace_id)
        output = self._confined(root, data.output, ".docx") if data.output else None
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
        try:
            built = deps.docx.build(resolved.doc_id, resolved.config, output)
        except ToolUnavailableError as exc:  # no pandoc, no sections to assemble: a result, not a server error
            return Response.json(dto.DocxBuildResponse(
                document_id=document_id, built=False, docx=None, message=self._clean(str(exc), root),
            ).model_dump())
        return Response.json(dto.DocxBuildResponse(
            document_id=document_id, built=True, docx=self._rel(root, built),
        ).model_dump())

    def format_audit_docx(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.FormatAuditRequest)
        root, deps, resolved = self._document(request, document_id, data.workspace_id)
        docx = self._quality.docx_input(request, root, deps, resolved, document_id, data.artifact_id, data.workspace_id)
        try:
            result = deps.format_audit.audit_format(docx, resolved.config, strict=data.strict)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
            raise APIError("docx_unreadable", self._clean(f"The DOCX cannot be audited: {exc}", root), 422) from exc
        return Response.json(dto.FormatAuditResponse(
            document_id=document_id, docx=self._rel(root, docx), strict=data.strict, passed=result.passed,
            issues=[issue.to_dict() for issue in result.issues], report=self._clean(result.to_markdown(), root),
        ).model_dump())

    # -- translate ---------------------------------------------------------------
    def translate(self, request: Request) -> Response:
        data = self._body(request, dto.TranslateRequest)
        root = Path(self._workspace_root(request, data.workspace_id)).resolve()
        deps = self._services_for(str(root))
        if not _LANGUAGE.fullmatch(data.to) or (data.source_lang != "auto" and not _LANGUAGE.fullmatch(data.source_lang)):
            raise APIError("invalid_language", "Language must be a code such as es, en or pt-BR", 400)
        uploaded = data.filename is not None and data.content_base64 is not None
        if (data.artifact_id is not None) == uploaded or (data.filename is None) != (data.content_base64 is None):
            raise APIError("invalid_source", "Provide either artifact_id or filename with content_base64", 400)
        staging = root / ".docs" / "staging" / uuid4().hex
        try:
            content = b""
            if data.artifact_id is not None:
                artifact, payload = self._quality._owned_artifact(request, data.artifact_id, data.workspace_id)
                source = self._quality._file(root, artifact, payload.get("document_id"))
                label = self._rel(root, source)
            else:
                try:
                    name, content = self._import.decode_upload(str(data.filename), str(data.content_base64))
                except ImportError as exc:
                    raise _import_error(exc) from exc
                source, label = staging / name, name
            if source.suffix.lower() != ".pdf":
                raise APIError("invalid_source", "The source must be a PDF", 400)
            if data.output:
                destination = self._confined(root, data.output, ".pdf")
                if not destination.is_relative_to((root / _TRANSLATIONS).resolve()):
                    raise APIError("output_not_permitted", f"Output must be inside {_TRANSLATIONS.as_posix()}", 400)
            else:
                destination = root / _TRANSLATIONS / f"{source.stem}.{data.to}.pdf"
            if destination.exists() and not data.overwrite:
                raise APIError("output_exists", "The output already exists; pass overwrite: true to replace it", 409)
            if data.artifact_id is None:
                staging.mkdir(parents=True)
                source.write_bytes(content)
            return self._translate(deps, root, source, label, destination, data)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _translate(
        self, deps: Any, root: Path, source: Path, label: str, destination: Path, data: dto.TranslateRequest,
    ) -> Response:
        memory_dir, pending_file = translation_sidecars(destination)
        service, translator = deps.build_translate_service(memory_dir, pending_file)
        if service is None:
            return Response.json(dto.TranslateResponse(
                status="unavailable", source=label,
                message="Translation unavailable: the PDF adapters (pypdfium2 / pdf-inspector) are missing.",
            ).model_dump())
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            report = service.translate_pdf(source, destination, data.to, data.source_lang)
        except UntranslatablePdfError as exc:
            return Response.json(dto.TranslateResponse(
                status="untranslatable", source=label, message=self._clean(str(exc), root),
            ).model_dump())
        written = translator.flush_pending(data.source_lang, data.to)
        return Response.json(dto.TranslateResponse(
            status="translated", source=label, output=self._rel(root, destination),
            pending=self._rel(root, written) if written is not None else None,
            report={
                "blocks_total": report.blocks_total, "blocks_translated": report.blocks_translated,
                "blocks_from_cache": report.blocks_from_cache, "blocks_untranslated": report.blocks_untranslated,
                "blocks_overflowed": report.blocks_overflowed, "blocks_rotated": report.blocks_rotated,
                "blocks_unsafe": report.blocks_unsafe, "pages_with_collisions": list(report.pages_with_collisions),
                "pages_untrusted": list(report.pages_untrusted), "fonts_substituted": report.fonts_substituted,
                "fonts_embedded": report.fonts_embedded, "fonts_unrecognized": report.fonts_unrecognized,
                "pending_blocks": int(getattr(translator, "pending_count", 0)),
                "write_diagnostics": [item.to_line() for item in report.write_diagnostics],
            },
            line=report.to_line(),
        ).model_dump())

    # -- diagnostics / issue codes / template catalogue ---------------------------
    def diagnostics(self, request: Request) -> Response:
        root = self._workspace_root(request, None)
        document_id = request.query.get("document_id") or self._services_for(root).documents.current()
        if not document_id:
            raise APIError("no_active_document", "No document is active; pass document_id", 409)
        root_path, deps, resolved = self._document(request, str(document_id), None)
        strict = request.query.get("strict", "").lower() in {"1", "true"}
        result = run_diagnostics(deps, resolved, strict=strict)
        checks = []
        for check in result.checks:
            match = _TRAILING_VERSION.search(check.detail) if check.name in _TOOLCHAIN else None
            checks.append(dto.DiagnosticCheck(
                name=check.name, status=_status(check.name, check.ok, check.required), required=check.required,
                detail=self._clean(check.detail, root_path), version=match.group(1) if match else None,
            ))
        return Response.json(dto.DiagnosticsResponse(
            document_id=str(document_id), passed=result.passed, strict=strict, checks=checks,
            capabilities=result.capabilities or {}, capability_diagnostics=result.capability_diagnostics or {},
        ).model_dump())

    def explain_issue_code(self, request: Request, code: str) -> Response:
        entry = ISSUE_CODES.get(code)
        if entry is None:
            raise APIError("issue_code_not_found", "Unknown issue code", 404)
        family = code.split(".")[0]
        return Response.json(dto.IssueCodeResponse(
            code=code, family=family, family_description=ISSUE_CODE_FAMILIES.get(family, ""),
            meaning=entry.meaning, fix=entry.fix,
        ).model_dump())

    def template_catalog(self, request: Request) -> Response:
        root = self._workspace_root(request, None)
        service = TemplateService(self._services_for(root).workspace.templates_dir)
        return Response.json(dto.TemplateCatalogResponse(items=[
            dto.TemplateCatalogItem(name=name, installed=service.path(name).is_file()) for name in builtin_names()
        ]).model_dump())
