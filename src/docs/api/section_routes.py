"""HTTP handlers for section authoring: build, pack, review, stamp and revise.

Same contract as `authoring_routes`: parse, resolve, call the canonical service
the CLI calls with the same inputs (normative settings and the rules-manifest
state come from `resolve_normative_settings` / `deps.rules_manifest_state`),
and map the result or exceptions to a DTO or `APIError`.  Long actions run
synchronously and return the paths of what they wrote, not a UI-inferred status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.authoring_clock import authoring_timestamp
from docs.domain.normative import resolve_normative_settings
from docs.domain.review import ReviewDimension, ReviewResult

from . import authoring_dto as dto
from .authoring_routes import RouteSupport, _safe_segment
from .http import APIError, Request, Response


def _relative(deps: Any, document_id: str, path: str | Path) -> str:
    root = Path(deps.workspace.doc_root(document_id)).resolve()
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _require_section(resolved: Any, section_id: str) -> None:
    if section_id not in {section.id for section in resolved.template.sections}:
        raise APIError("section_not_found", "Section not found", 404)


class SectionRoutes(RouteSupport):
    def _open_resolved(
        self, request: Request, document_id: str, workspace_id: str | None, section_id: str | None = None,
    ) -> tuple[Any, Any]:
        _, deps = self._open(request, document_id, workspace_id)
        resolved = self._resolve(deps, document_id)
        if section_id is not None:
            _safe_segment(section_id, "invalid_section")
            _require_section(resolved, section_id)
        return deps, resolved

    @staticmethod
    def _review_response(document_id: str, section_id: str | None, result: ReviewResult) -> Response:
        return Response.json(dto.ReviewResponse(
            document_id=document_id, section_id=section_id, passed=result.passed,
            findings=[dto.ReviewFinding(**issue.to_dict()) for issue in result.issues],  # type: ignore[arg-type]
        ).model_dump())

    # -- build / pack --------------------------------------------------------
    def build_section(self, request: Request, document_id: str, section_id: str) -> Response:
        data = self._body(request, dto.WorkspaceScopedRequest)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id, section_id)
        try:
            path = deps.section.build_section(resolved.doc_id, resolved.template, section_id, resolved.config)
        except FileNotFoundError as exc:
            raise APIError("section_not_found", str(exc), 404) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise APIError("build_failed", str(exc), 400) from exc
        section = next(s for s in resolved.template.sections if s.id == section_id)
        canonical = deps.review.repository.section_path(resolved.doc_id, section.order, section.id)
        return Response.json(dto.SectionBuildResponse(
            document_id=document_id, section_id=section_id,
            path=_relative(deps, document_id, path),
            proposal=Path(path).resolve() != Path(canonical).resolve(),
        ).model_dump())

    def pack_context(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.ContextPackRequest)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id)
        target = data.target
        if target not in {"all", "document"}:
            _safe_segment(target, "invalid_section")
            _require_section(resolved, target)
        normative = resolve_normative_settings(resolved.config)
        packer = deps.context_pack
        paths: list[str | Path] = []
        try:
            if target == "all":
                paths += [
                    packer.pack_context(resolved.doc_id, resolved.template, s.id, resolved.config, normative=normative)
                    for s in resolved.template.sections
                ]
            if target in {"all", "document"}:
                manifest_exists, manifest_size = deps.rules_manifest_state(resolved.config)
                paths.append(packer.pack_context_document(
                    resolved.doc_id, resolved.template, resolved.config,
                    manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
                ))
            else:
                paths.append(packer.pack_context(
                    resolved.doc_id, resolved.template, target, resolved.config, normative=normative,
                ))
        except (ValueError, KeyError, OSError) as exc:
            raise APIError("pack_failed", str(exc), 400) from exc
        return Response.json(dto.ContextPackResponse(
            document_id=document_id, target=target, paths=[_relative(deps, document_id, p) for p in paths],
        ).model_dump())

    # -- review / stamp ------------------------------------------------------
    def review_section(self, request: Request, document_id: str, section_id: str) -> Response:
        data = self._body(request, dto.ReviewRequest)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id, section_id)
        normative = resolve_normative_settings(resolved.config)
        try:
            result = deps.review.review_section(
                resolved.doc_id, resolved.template, section_id, strict=data.strict, normative=normative,
            )
        except FileNotFoundError as exc:
            raise APIError("section_not_found", str(exc), 404) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise APIError("review_failed", str(exc), 400) from exc
        return self._review_response(document_id, section_id, result)

    def review_document(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.DocumentReviewRequest)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id)
        normative = resolve_normative_settings(resolved.config)
        manifest_exists, manifest_size = deps.rules_manifest_state(resolved.config)
        try:
            result = deps.review.review_document(
                resolved.doc_id, resolved.template, strict=data.strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            )
        except FileNotFoundError as exc:
            raise APIError("document_not_found", str(exc), 404) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise APIError("review_failed", str(exc), 400) from exc
        if data.dimensions:
            result = result.filter_dimensions({ReviewDimension(d) for d in data.dimensions})
        return self._review_response(document_id, None, result)

    def stamp_section(self, request: Request, document_id: str, section_id: str) -> Response:
        data = self._body(request, dto.StampRequest)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id, section_id)
        now = authoring_timestamp()
        try:
            path = deps.review.stamp_section(
                resolved.doc_id, resolved.template, section_id, authored_by=data.by, model=data.model, now=now,
            )
        except FileNotFoundError as exc:
            raise APIError("section_not_found", str(exc), 404) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise APIError("stamp_failed", str(exc), 400) from exc
        return Response.json(dto.StampResponse(
            document_id=document_id, section_id=section_id, path=_relative(deps, document_id, path),
            authored_by=data.by, model=data.model, stamped_at=now,
        ).model_dump())

    # -- revise (`doc revise`) -------------------------------------------------
    def revise(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.RevisionRequest)
        value = data.new_body if data.new_body is not None else data.new_value
        if value is None:
            raise APIError("invalid_request", "new_body or new_value is required", 400)
        deps, resolved = self._open_resolved(request, document_id, data.workspace_id)
        normative = resolve_normative_settings(resolved.config)
        manifest_exists, manifest_size = deps.rules_manifest_state(resolved.config)
        now = authoring_timestamp()
        common = {
            "strict": data.strict, "manifest_exists": manifest_exists, "manifest_size": manifest_size,
            "normative": normative, "now": now,
        }
        try:
            if deps.revision.resolve_target(resolved.template, data.target_id) == "section":
                result = deps.revision.revise(
                    resolved.doc_id, resolved.template, resolved.config, data.target_id, value, data.request, **common,
                )
            else:
                result = deps.revision.revise_topic(
                    resolved.doc_id, resolved.template, resolved.config, data.target_id, value, data.request,
                    field=data.field, **common,
                )
        except (ValueError, FileNotFoundError) as exc:
            raise APIError("invalid_revision", str(exc), 400) from exc
        return Response.json(dto.RevisionResponse(
            target_id=result.target_id, diff=result.diff, summary=result.summary,
            changed_sections=list(result.changed_sections),
            diff_path=_relative(deps, document_id, result.diff_path) if result.diff_path else "",
        ).model_dump(), 201)
