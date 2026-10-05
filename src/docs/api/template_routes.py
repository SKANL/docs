"""HTTP handlers for template administration: adapters over `TemplateService`, the service the CLI calls.

Writes land in the workspace templates directory only; responses carry
workspace-relative paths, never absolute ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.templates import TemplateError, TemplateService

from . import authoring_dto as dto
from .authoring_routes import RouteSupport
from .http import APIError, Request, Response

_STATUS = {
    "invalid_template_name": 400,
    "template_not_found": 404,
    "builtin_template_not_found": 404,
    "template_exists": 409,
}


class TemplateRoutes(RouteSupport):
    def _service(self, request: Request, workspace_id: str | None) -> tuple[TemplateService, Any]:
        deps = self._services_for(self._workspace_root(request, workspace_id))
        return TemplateService(deps.workspace.templates_dir), deps

    @staticmethod
    def _fail(exc: TemplateError, service: TemplateService) -> APIError:
        message = str(exc).replace(str(service.templates_dir), service.templates_dir.name)
        return APIError(exc.code, message, _STATUS.get(exc.code, 400))

    @staticmethod
    def _written(service: TemplateService, name: str, path: Path) -> dto.TemplateWriteResponse:
        return dto.TemplateWriteResponse(name=name, path=f"{service.templates_dir.name}/{path.name}")

    def show_template(self, request: Request, template_name: str) -> Response:
        service, deps = self._service(request, None)
        try:
            service.path(template_name)
        except TemplateError as exc:
            raise self._fail(exc, service) from exc
        try:
            template = deps.document_repository.load_template(template_name)
        except FileNotFoundError as exc:
            raise APIError("template_not_found", "Template not found", 404) from exc
        except ValueError as exc:  # stored file is not a loadable template
            raise APIError("template_invalid", "Template cannot be loaded", 422) from exc
        return Response.json(dto.TemplateShowResponse(name=template_name, template=template.model_dump()).model_dump())

    def use_template(self, request: Request, template_name: str) -> Response:
        data = self._body(request, dto.TemplateUseRequest)
        service, _ = self._service(request, data.workspace_id)
        try:
            path = service.use(template_name, force=data.force)
        except TemplateError as exc:
            raise self._fail(exc, service) from exc
        return Response.json(self._written(service, template_name, path).model_dump())

    def create_template(self, request: Request) -> Response:
        data = self._body(request, dto.TemplateCreateRequest)
        service, _ = self._service(request, data.workspace_id)
        try:
            path = service.create(data.name)
        except TemplateError as exc:
            raise self._fail(exc, service) from exc
        return Response.json(self._written(service, data.name, path).model_dump(), 201)

    def validate_template(self, request: Request, template_name: str) -> Response:
        data = self._body(request, dto.TemplateValidateRequest)
        service, _ = self._service(request, data.workspace_id)
        try:
            service.path(template_name)
            result = service.validate_raw(data.template) if data.template is not None else service.validate(template_name)
        except TemplateError as exc:
            raise self._fail(exc, service) from exc
        return Response.json(dto.TemplateValidationResponse(
            name=template_name, passed=result.passed, issues=[issue.to_dict() for issue in result.issues],
        ).model_dump())
