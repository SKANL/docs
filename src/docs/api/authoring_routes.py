"""HTTP handlers for source, asset, classification, and context workflows.

Handlers only parse and validate the request, resolve workspace and document,
call the canonical application service, and map its result or exceptions to a
DTO or `APIError`.  The services are the same ones the CLI composes.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import ValidationError

from docs.application.classification_queue import (
    ClassificationQueueError,
    ClassificationQueueUnavailable,
    review_classification_queue,
)
from docs.application.document_summary import build_document_summary
from docs.application.imports import ImportError, SourceImportService
from docs.domain.ports.document_repository import DocumentNotFoundError

from . import authoring_dto as dto
from .http import APIError, Request, Response

_M = TypeVar("_M", bound=dto.AuthoringDTO)

# Ids that survive `SourceImportService`'s document-id normalisation unchanged.
_UPLOAD_DOCUMENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_CONTROL = re.compile(r"[\x00-\x1f]")


def _safe_segment(value: str, code: str) -> str:
    """Reject anything that is not a single plain path segment."""
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or Path(value).name != value
        or _CONTROL.search(value)
    ):
        raise APIError(code, "Invalid name", 400)
    return value


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=False)


class RouteSupport:
    """Request parsing and document resolution shared by every operation handler."""

    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
    ) -> None:
        self._workspace_root = workspace_root
        self._services_for = services_for

    @staticmethod
    def _body(request: Request, model: type[_M]) -> _M:
        data = request.json(object_only=True) if request.body else {}
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise APIError("invalid_request", "Invalid request body", 400) from exc

    def _open(self, request: Request, document_id: str, body_workspace: str | None = None) -> tuple[str, Any]:
        _safe_segment(document_id, "invalid_document_id")
        root = self._workspace_root(request, body_workspace)
        deps = self._services_for(root)
        if not deps.document_repository.exists(document_id):
            raise APIError("document_not_found", "Document not found", 404)
        return root, deps

    @staticmethod
    def _resolve(deps: Any, document_id: str) -> Any:
        try:
            return deps.resolve_context(document_id)
        except (DocumentNotFoundError, FileNotFoundError) as exc:
            raise APIError("document_not_found", "Document not found", 404) from exc
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            raise APIError("document_unresolvable", str(exc), 400) from exc


class AuthoringRoutes(RouteSupport):
    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
        import_service: SourceImportService,
    ) -> None:
        super().__init__(workspace_root=workspace_root, services_for=services_for)
        self._import = import_service

    # -- summary / import ---------------------------------------------------
    def document_summary(self, request: Request, document_id: str) -> Response:
        _, deps = self._open(request, document_id)
        self._resolve(deps, document_id)  # a bad document is a 4xx, never a 500
        _, payload = build_document_summary(deps, document_id)
        return Response.json(dto.DocumentSummaryResponse(document_id=document_id, summary=_jsonable(payload)).model_dump())

    def import_document_source(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.DocumentImportRequest)
        root, _ = self._open(request, document_id, data.workspace_id)
        try:
            stored = self._import.import_base64(root, data.filename, data.content_base64, document_id=document_id)
        except ImportError as exc:
            raise APIError(str(exc), str(exc), 400) from exc
        except OSError as exc:
            raise APIError("upload_failed", "Could not store the source", 500) from exc
        return Response.json(dto.DocumentImportResponse(
            document_id=document_id, filename=stored["filename"],
            path=Path(stored["path"]).resolve().relative_to(Path(root).resolve()).as_posix(),
            sha256=stored["sha256"], size=stored["size"], mime_type=stored["mime_type"],
            deduplicated=stored["deduplicated"],
        ).model_dump(), 201)

    # -- assets ------------------------------------------------------------
    def list_assets(self, request: Request, document_id: str) -> Response:
        _, deps = self._open(request, document_id)
        kind = str(request.query.get("kind", "docx"))
        try:
            names = deps.assets.list_assets(document_id, kind)
        except ValueError as exc:
            raise APIError("invalid_asset_kind", str(exc), 400) from exc
        return Response.json(dto.AssetListResponse(
            document_id=document_id, kind=kind, items=[dto.AssetItem(name=n) for n in names],
        ).model_dump())

    def add_asset(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.AssetAddRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        try:
            filename, content = self._import.decode_upload(data.filename, data.content_base64)
        except ImportError as exc:
            raise APIError(str(exc), str(exc), 400) from exc
        if data.name:
            _safe_segment(data.name, "invalid_filename")
        staging = Path(root) / ".docs" / "staging" / uuid4().hex
        try:
            staging.mkdir(parents=True)
            staged = staging / filename
            staged.write_bytes(content)
            target = deps.assets.add_asset(document_id, str(staged), name=data.name)
        except (ValueError, FileNotFoundError) as exc:
            raise APIError("invalid_asset", str(exc), 400) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        relative = Path(target).resolve().relative_to(deps.workspace.doc_root(document_id).resolve())
        return Response.json(dto.AssetResponse(
            document_id=document_id, name=Path(target).stem, path=relative.as_posix(),
        ).model_dump(), 201)

    def remove_asset(self, request: Request, document_id: str, asset_name: str) -> Response:
        _, deps = self._open(request, document_id)
        _safe_segment(asset_name, "invalid_filename")
        try:
            present = {n.casefold() for n in deps.assets.list_assets(document_id, str(request.query.get("kind", "docx")))}
        except ValueError as exc:
            raise APIError("invalid_asset_kind", str(exc), 400) from exc
        if asset_name.casefold() not in present and Path(asset_name).stem.casefold() not in present:
            raise APIError("asset_not_found", "Asset not found", 404)
        try:
            deps.assets.remove_asset(document_id, asset_name)
        except ValueError as exc:
            raise APIError("invalid_asset", str(exc), 400) from exc
        return Response.json(dto.AssetRemoveResponse(document_id=document_id, removed=asset_name).model_dump())

    # -- sources -------------------------------------------------------------
    def ingest_sources(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.SourceIngestRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        if data.files and not _UPLOAD_DOCUMENT_ID.fullmatch(document_id):
            raise APIError("invalid_document_id", "Document id cannot receive uploads", 400)
        resolved = self._resolve(deps, document_id)  # before any write: a bad document leaves no uploads
        try:  # validate every upload before writing any of them
            decoded = [self._import.decode_upload(f.filename, f.content_base64) for f in data.files]
        except ImportError as exc:
            raise APIError(str(exc), str(exc), 400) from exc
        uploaded: list[dto.UploadedSource] = []
        created: list[Path] = []  # files this request wrote, removed again if a later upload fails
        try:
            for filename, content in decoded:
                stored = self._import.import_bytes(root, filename, content, document_id=document_id)
                if not stored["deduplicated"]:
                    created.append(Path(stored["path"]))
                uploaded.append(dto.UploadedSource(
                    filename=stored["filename"], sha256=stored["sha256"],
                    size=stored["size"], deduplicated=stored["deduplicated"],
                ))
        except (ImportError, OSError) as exc:
            for path in created:
                path.unlink(missing_ok=True)
            code = str(exc) if isinstance(exc, ImportError) else "upload_failed"
            raise APIError(code, str(exc), 400 if isinstance(exc, ImportError) else 500) from exc
        try:
            report = deps.create_source_pipeline().ingest(
                document_id, deps.workspace.doc_root(document_id), resolved.config,
            )
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise APIError("ingest_failed", str(exc), 400) from exc
        except (OSError, RuntimeError) as exc:
            raise APIError("ingest_failed", str(exc), 500) from exc
        return Response.json(self._ingest_response(document_id, report, uploaded).model_dump())

    @staticmethod
    def _ingest_response(document_id: str, report: Mapping[str, Any], uploaded: list[dto.UploadedSource]) -> dto.SourceIngestResponse:
        stages = []
        for stage in report.get("stages", ()):
            result = stage.get("result") if isinstance(stage.get("result"), Mapping) else {}
            processed = result.get("processed")
            stages.append(dto.IngestStage(
                name=str(stage.get("name", "")),
                succeeded=bool(stage.get("succeeded")),
                status=str(result["status"]) if result.get("status") is not None else None,
                processed=processed if isinstance(processed, int) and not isinstance(processed, bool) else None,
                errors=[_text(e) for e in result.get("errors") or ()],
                warnings=[_text(w) for w in result.get("warnings") or ()],
                files=[_jsonable(f) for f in result.get("files") or () if isinstance(f, Mapping)],
            ))
        return dto.SourceIngestResponse(
            document_id=document_id,
            succeeded=bool(report.get("succeeded")),
            artifacts=[str(a) for a in report.get("artifacts", ())],
            uploaded=uploaded,
            stages=stages,
        )

    # -- classification (existing routes, shared application function) ----
    def classification(self, request: Request, document_id: str) -> Response:
        confirm = self._body(request, dto.ClassificationConfirmRequest) if request.method.upper() == "POST" else None
        _, deps = self._open(request, document_id, confirm.workspace_id if confirm else None)
        try:
            entries = review_classification_queue(
                deps.workspace.doc_root(document_id),
                confirm.relative_path if confirm else None,
                confirm.confirmed_role if confirm else None,
            )
        except ClassificationQueueUnavailable as exc:
            raise APIError("classification_unavailable", str(exc), 404) from exc
        except ClassificationQueueError as exc:
            raise APIError("invalid_classification", str(exc), 400) from exc
        return Response.json(dto.ClassificationResponse(document_id=document_id, items=entries).model_dump())

    # -- context -------------------------------------------------------------
    def elicit_context(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.ContextElicitRequest)
        _, deps = self._open(request, document_id, data.workspace_id)
        resolved = self._resolve(deps, document_id)
        try:
            path = deps.context.write_requests_file(document_id, resolved.template, only_topic=data.topic)
        except ValueError as exc:
            raise APIError("invalid_context", str(exc), 400) from exc
        return Response.json(dto.ContextRequestsResponse(
            document_id=document_id,
            path=Path(path).resolve().relative_to(deps.workspace.doc_root(document_id).resolve()).as_posix(),
            markdown=Path(path).read_text(encoding="utf-8"),
        ).model_dump())

    def ingest_context(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.WorkspaceScopedRequest)
        _, deps = self._open(request, document_id, data.workspace_id)
        resolved = self._resolve(deps, document_id)
        try:
            written = deps.context.ingest(document_id, resolved.template)
        except FileNotFoundError as exc:
            raise APIError("context_requests_missing", str(exc), 404) from exc
        return Response.json(dto.ContextIngestResponse(document_id=document_id, topics=list(written)).model_dump())

    def _known_topic(self, deps: Any, document_id: str, topic_id: str) -> None:
        _safe_segment(topic_id, "invalid_topic")
        schema = self._resolve(deps, document_id).template.context_schema
        if topic_id not in {topic.id for topic in schema.topics}:
            raise APIError("topic_not_found", "Context topic not found", 404)

    def show_context_topic(self, request: Request, document_id: str, topic_id: str) -> Response:
        _, deps = self._open(request, document_id)
        self._known_topic(deps, document_id, topic_id)
        try:
            content = deps.context.show(document_id, topic_id)
        except FileNotFoundError as exc:
            raise APIError("topic_not_found", "Context topic has no saved content", 404) from exc
        return Response.json(dto.ContextTopicResponse(
            document_id=document_id, topic=topic_id, content=content,
        ).model_dump())

    def remove_context_topic(self, request: Request, document_id: str, topic_id: str) -> Response:
        _, deps = self._open(request, document_id)
        self._known_topic(deps, document_id, topic_id)
        template = self._resolve(deps, document_id).template
        try:
            deps.context.remove(document_id, template, topic_id)
        except (FileNotFoundError, KeyError) as exc:
            raise APIError("topic_not_found", "Context topic has no saved content", 404) from exc
        except ValueError as exc:
            raise APIError("invalid_context", str(exc), 400) from exc
        return Response.json(dto.ContextRemoveResponse(document_id=document_id, removed=topic_id).model_dump())
