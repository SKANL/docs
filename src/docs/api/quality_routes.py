"""HTTP handlers for visual quality: evidence, baseline promotion, inspect, diff, qa-docx, corrections.

Thin adapters over the services the CLI calls.  HTTP never takes a filesystem
path: it takes run and artifact ids, resolves them through the stores, and only
serves/reads files that resolve inside the workspace.  Responses carry ids,
sha256 digests and workspace-relative paths, never raw file contents or
absolute paths.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from docs.application.visual_baseline import VisualBaselineError, VisualBaselineService
from docs.domain.paths import PathEscapeError, require_within

from . import authoring_dto as dto
from .auth import require_scopes
from .authoring_routes import RouteSupport, _safe_segment
from .http import APIError, Request, Response


def _dict(value: Any) -> dict[str, Any]:
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_path(artifact: Mapping[str, Any]) -> str | None:
    """The file a pipeline stage recorded; the sqlite store may stringify the record."""
    metadata = artifact.get("metadata")
    raw = metadata.get("value") if isinstance(metadata, Mapping) else None
    try:
        record = ast.literal_eval(raw) if isinstance(raw, str) else raw
    except (ValueError, SyntaxError):
        return None
    path = record.get("path") if isinstance(record, Mapping) else None
    return str(path) if path else None


def _is_png(artifact: Mapping[str, Any]) -> bool:
    return artifact.get("media_type") == "image/png" or (_recorded_path(artifact) or "").lower().endswith(".png")


class QualityRoutes(RouteSupport):
    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
        host: Any,
    ) -> None:
        super().__init__(workspace_root=workspace_root, services_for=services_for)
        self._host = host  # the X20Application: run/artifact/passport/finding stores + ownership

    # -- shared resolution ---------------------------------------------------
    @staticmethod
    def _workspace_id(request: Request, body_workspace: str | None) -> str:
        return str(request.query.get("workspace_id") or body_workspace or "")

    def _owned_run(self, request: Request, run_id: str, body_workspace: str | None) -> Any:
        run = self._host.run_store.get(run_id)
        payload = _dict(run).get("payload", {}) if run is not None else {}
        if run is None or payload.get("workspace_id") != self._workspace_id(request, body_workspace):
            raise APIError("not_found", "Run not found", 404)
        self._host._require_owned(run, request, "Run")
        return run

    def _owned_artifact(self, request: Request, artifact_id: str, body_workspace: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        found = self._host.artifact_store.get(artifact_id)
        if found is None:
            raise APIError("not_found", "Artifact not found", 404)
        artifact = _dict(found)
        run = self._owned_run(request, str(artifact.get("run_id", "")), body_workspace)
        return artifact, _dict(run).get("payload", {})

    @staticmethod
    def _locate(root: Path, artifact: Mapping[str, Any], document_id: str | None) -> Path | None:
        """The recorded file when it exists; `None` when not materialized; error when it escapes."""
        raw = _recorded_path(artifact)
        if raw is None:
            return None
        candidate = Path(raw)
        options = [candidate] if candidate.is_absolute() else [
            *([root / "documents" / document_id / candidate] if document_id else []), root / candidate,
        ]
        for option in options:
            resolved = option.resolve()
            try:
                require_within(resolved, root)
            except PathEscapeError as exc:
                raise APIError("artifact_outside_workspace", "Artifact is outside the workspace", 400) from exc
            if resolved.is_file():
                return resolved
        return None

    def _file(self, root: Path, artifact: Mapping[str, Any], document_id: str | None) -> Path:
        path = self._locate(root, artifact, document_id)
        if path is None:
            raise APIError("artifact_unavailable", "Artifact file is not materialized", 409)
        return path

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return path.relative_to(root).as_posix()

    def _root(self, request: Request, body_workspace: str | None) -> Path:
        return Path(self._workspace_root(request, body_workspace)).resolve()

    # -- evidence ------------------------------------------------------------
    def run_evidence(self, request: Request, run_id: str) -> Response:
        self._root(request, None)
        self._owned_run(request, run_id, None)
        if request.principal is not None:  # the bundle discloses artifacts and findings too
            require_scopes(request.principal, "artifacts:read", "findings:read")
        passport = self._host.passport_store.get(run_id)
        if passport is None:
            raise APIError("not_found", "Passport not found", 404)
        records = sorted(
            (_dict(item) for item in self._host._store_items(self._host.artifact_store, "list_for_run", run_id)),
            key=lambda item: str(item["id"]),
        )
        refs = [
            dto.EvidenceArtifactRef(id=a["id"], kind=a["kind"], digest=a["digest"], media_type=a.get("media_type", ""))
            for a in records
        ]
        findings = sorted(
            (_dict(item) for item in self._host._store_items(self._host.findings_store, "list_for_run", run_id)),
            key=lambda item: str(item.get("id", "")),
        )
        previews = [a["id"] for a in records if _is_png(a)]
        evidence = {"passport": _dict(passport), "artifacts": [r.model_dump() for r in refs], "findings": findings}
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        return Response.json(dto.EvidenceBundleResponse(
            run_id=run_id, evidence_sha256=digest, passport=_dict(passport), artifacts=refs, findings=findings,
            previews=dto.PreviewAvailability(available=bool(previews), artifact_ids=previews),
        ).model_dump())

    # -- baseline ------------------------------------------------------------
    def promote_baseline(self, request: Request) -> Response:
        data = self._body(request, dto.BaselinePromotionRequest)
        root = self._root(request, data.workspace_id)
        run = self._owned_run(request, data.run_id, data.workspace_id)
        name = _safe_segment(data.name or data.run_id, "invalid_baseline_name")
        document_id = _dict(run).get("payload", {}).get("document_id")
        records = (_dict(a) for a in self._host._store_items(self._host.artifact_store, "list_for_run", data.run_id))
        located = [self._locate(root, a, document_id) for a in records if _is_png(a)]
        sources = {path.parent for path in located if path is not None}
        if not sources:
            raise APIError("previews_unavailable", "The run has no rendered previews to promote", 409)
        if len(sources) > 1:
            raise APIError("previews_ambiguous", "The run's previews are spread over several directories", 409)
        destination = root / "baselines" / name
        replaced = destination.exists()
        if replaced and not data.update:
            raise APIError("baseline_exists", "Baseline already exists; pass update to replace it", 409)
        try:
            published = VisualBaselineService().update(sources.pop(), destination, overwrite=data.update)
        except VisualBaselineError as exc:
            raise APIError("baseline_rejected", str(exc).replace(str(root), "."), 409) from exc
        return Response.json(dto.BaselinePromotionResponse(
            run_id=data.run_id, name=name, destination=self._relative(root, destination), replaced=replaced,
            pages=[dto.BaselinePage(name=p.name, sha256=_sha(p)) for p in published],
        ).model_dump(), 201)

    # -- inspect / diff ------------------------------------------------------
    def _report(self, root: Path, deps: Any, path: Path) -> dict[str, Any]:
        report = dict(deps.artifact_reports.inspect(path))
        report["path"] = self._relative(root, path)
        return report

    def inspect_artifact(self, request: Request, artifact_id: str) -> Response:
        root = self._root(request, None)
        artifact, payload = self._owned_artifact(request, artifact_id, None)
        path = self._file(root, artifact, payload.get("document_id"))
        report = self._report(root, self._services_for(str(root)), path)
        return Response.json(dto.ArtifactInspectResponse(artifact_id=artifact_id, **report).model_dump())

    def diff_artifacts(self, request: Request) -> Response:
        data = self._body(request, dto.ArtifactDiffRequest)
        root = self._root(request, data.workspace_id)
        deps = self._services_for(str(root))
        paths = []
        for artifact_id in (data.left, data.right):
            artifact, payload = self._owned_artifact(request, artifact_id, data.workspace_id)
            paths.append(self._file(root, artifact, payload.get("document_id")))
        result = dict(deps.artifact_reports.compare(*paths))
        result["left"], result["right"] = (self._report(root, deps, p) for p in paths)
        lines = list(result["text_diff"])
        if len(lines) >= 2:  # unified_diff headers name the files; keep them workspace-relative
            lines[0], lines[1] = f"--- {result['left']['path']}\n", f"+++ {result['right']['path']}\n"
        result["text_diff"] = lines  # ponytail: unbounded, cap/paginate if artifacts get large
        return Response.json(dto.ArtifactDiffResponse(**result).model_dump())

    # -- qa-docx / corrections -------------------------------------------------
    def docx_input(
        self, request: Request, root_path: Path, deps: Any, resolved: Any, document_id: str,
        artifact_id: str | None, body_workspace: str | None,
    ) -> Path:
        """The DOCX a tool works on: a workspace artifact of this document, else its built draft."""
        if artifact_id:
            artifact, payload = self._owned_artifact(request, artifact_id, body_workspace)
            if payload.get("document_id") not in (None, document_id):
                raise APIError("not_found", "Artifact not found", 404)
            docx = self._file(root_path, artifact, document_id)
            if docx.suffix.lower() != ".docx":
                raise APIError("invalid_artifact", "Artifact is not a .docx", 400)
            return docx
        name = deps.docx._draft_docx_name(resolved.doc_id, resolved.config)
        draft_dir = Path(resolved.config["paths"]["output_draft_dir"])
        if not draft_dir.is_absolute():  # never resolve against the process cwd
            draft_dir = Path(deps.workspace.doc_root(document_id)) / draft_dir
        docx = (draft_dir / name).resolve()
        try:
            require_within(docx, root_path)
        except PathEscapeError as exc:
            raise APIError("artifact_outside_workspace", "Built DOCX is outside the workspace", 400) from exc
        if not docx.is_file():
            raise APIError("docx_unavailable", "The document has no built DOCX; build it first", 409)
        return docx

    def qa_docx(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.QaDocxRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        root_path = Path(root).resolve()
        resolved = self._resolve(deps, document_id)
        docx = self.docx_input(request, root_path, deps, resolved, document_id, data.artifact_id, data.workspace_id)
        out: Path | None = None
        message: str | None = None
        try:
            out = Path(deps.qa.qa_docx(resolved.config, docx, strict=data.strict))
        except RuntimeError as exc:  # strict warnings, render failures: a result, not a server error
            message = str(exc).replace(root, ".")
        except ValueError as exc:
            raise APIError("invalid_qa_profile", str(exc), 400) from exc
        report = out / "qa-report.md" if out is not None else None
        degraded = out is not None and not any(out.glob("*.pdf"))  # no render = the visual QA never ran
        return Response.json(dto.QaDocxResponse(
            document_id=document_id, docx=self._relative(root_path, docx), strict=data.strict,
            passed=out is not None, message=message, degraded=degraded,
            degraded_reason="render.capability.unavailable" if degraded else None,
            report=self._relative(root_path, report.resolve()) if report is not None and report.is_file() else None,
        ).model_dump())

    def apply_corrections(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.WorkspaceScopedRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        resolved = self._resolve(deps, document_id)
        try:
            applied = deps.corrections.apply_corrections(resolved.doc_id, resolved.config)
        except (RuntimeError, ValueError, KeyError) as exc:
            raise APIError("invalid_correction", str(exc).replace(root, "."), 400) from exc
        return Response.json(dto.CorrectionsResponse(document_id=document_id, applied=applied).model_dump())
