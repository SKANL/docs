"""HTTP handlers for the pipeline: resolved plan and durable run creation.

`plan` calls the same `describe_pipeline` the CLI calls.  `run` enqueues
through the application's single run-creation path (the one behind
`/v2/documents/{id}/build`), so HTTP never orchestrates stages itself.  HTTP is
always asynchronous and watched: the CLI's `--sync/--async/--watch` are
transport modes, and the client follows `links.progress`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from docs.application.pipeline_plan import describe_pipeline
from docs.domain.runtime_records import Run

from . import authoring_dto as dto
from .authoring_routes import RouteSupport
from .http import APIError, Request, Response

SUPPORTED_OUTPUT_FORMATS = frozenset({"docx", "pdf", "html"})


def output_format(value: object) -> str:
    name = str(value or "docx").strip().lower()
    if name not in SUPPORTED_OUTPUT_FORMATS:
        raise APIError(
            "invalid_output_format",
            f"format must be one of: {', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))}",
            400,
        )
    return name


class PipelineRoutes(RouteSupport):
    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
        enqueue: Callable[[Request, dict[str, Any]], Run],
    ) -> None:
        super().__init__(workspace_root=workspace_root, services_for=services_for)
        self._enqueue = enqueue

    @staticmethod
    def _plan(deps: Any, document_id: str, pipeline_id: str, fmt: str) -> dict[str, Any]:
        try:
            service = deps.create_document_pipeline_service(fmt, document=document_id, pipeline_id=pipeline_id)
            return describe_pipeline(service, pipeline_id)
        except KeyError as exc:
            raise APIError("unknown_pipeline", f"Unknown pipeline: {pipeline_id}", 400) from exc

    def plan_document(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.PipelinePlanRequest)
        _, deps = self._open(request, document_id, data.workspace_id)
        plan = self._plan(deps, document_id, data.pipeline_id, output_format(data.format))
        return Response.json(dto.PipelinePlanResponse(document_id=document_id, **plan).model_dump())

    def run_document(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.PipelineRunRequest)
        if data.strict and data.release:
            raise APIError("invalid_request", "strict and release are mutually exclusive", 400)
        _, deps = self._open(request, document_id, data.workspace_id)
        configured = (self._resolve(deps, document_id).config or {}).get("output", {})
        fmt = output_format(data.format or (configured.get("format") if isinstance(configured, dict) else None))
        self._plan(deps, document_id, data.pipeline_id, fmt)  # rejects an unknown pipeline before queueing
        policy = data.policy or ("strict" if data.strict else "release")
        run = self._enqueue(request, {
            "workspace_id": request.query.get("workspace_id") or data.workspace_id,
            "document_id": document_id,
            "pipeline_id": data.pipeline_id,
            "format": fmt,
            "policy": policy,
        })
        base = f"/v2/runs/{run.id}"
        return Response.json(dto.PipelineRunResponse(
            id=run.id, status=run.status, document_id=document_id, pipeline_id=data.pipeline_id,
            format=fmt, policy=policy,
            links=dto.RunLinks(self=base, progress=f"{base}/progress", cancel=f"{base}/cancel"),
        ).model_dump(), 202)
