"""HTTP handlers for delivery: package a build output, publish one verified artifact.

Thin adapters over `PackagePublicationService`, the service the CLI calls.
HTTP never takes a filesystem path: a package is cut from the document's own
`output/current`, a publication goes to a *relative* destination under the
document's `output/release`, and the archive is written by the service's
deterministic writer, never here.  Responses carry workspace-relative paths and
sha256 digests only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docs.application.document_pipeline import _current_input_identities, _resolve_publish_inputs
from docs.application.package_publication_service import PackagePublicationError, PublishPolicyDeniedError
from docs.domain.identity import sha256_bytes
from docs.domain.paths import confine_or_raise
from docs.domain.pipeline_policy import PipelineMode
from docs.domain.ports.document_repository import DocumentNotFoundError

from . import authoring_dto as dto
from .authoring_routes import RouteSupport, _jsonable, _safe_segment
from .http import APIError, Request, Response
from .pipeline_routes import output_format


class DeliveryRoutes(RouteSupport):
    def __init__(
        self,
        *,
        workspace_root: Callable[[Request, str | None], str],
        services_for: Callable[[str], Any],
        owned_run: Callable[[Request, str, str | None], Any],
        publications: Callable[[], Any],
    ) -> None:
        super().__init__(workspace_root=workspace_root, services_for=services_for)
        self._owned_run = owned_run
        self._publications = publications  # the publication store, resolved lazily (may be None)

    @staticmethod
    def _rel(root: Path, path: Path) -> str:
        return path.resolve().relative_to(root).as_posix()

    @staticmethod
    def _clean(message: str, root: Path) -> str:
        return message.replace(str(root), ".")

    # -- package -------------------------------------------------------------
    def package_document(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.PackageRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        ws = Path(root).resolve()
        if data.run_id:
            run = self._owned_run(request, data.run_id, data.workspace_id)
            if run.to_dict().get("payload", {}).get("document_id") != document_id:
                raise APIError("not_found", "Run not found", 404)
        name = _safe_segment(data.name or data.run_id or "current", "invalid_package_name")
        source = (deps.workspace.doc_root(document_id) / "output" / "current").resolve()
        if not source.is_dir():
            raise APIError("package_source_unavailable", "The document has no build output; build it first", 409)
        output = ws / "artifacts" / "packages" / f"{document_id}-{name}.zip"
        try:
            deps.package_publications.package(output, source)
        except PackagePublicationError as exc:
            raise APIError("package_rejected", self._clean(str(exc), ws), 409) from exc
        archive = output.read_bytes()
        return Response.json(dto.PackageResponse(
            document_id=document_id, run_id=data.run_id, source=self._rel(ws, source),
            destination=self._rel(ws, output), sha256=sha256_bytes(archive), size_bytes=len(archive),
        ).model_dump())

    # -- publish -------------------------------------------------------------
    @staticmethod
    def _destination(release: Path, requested: str) -> Path:
        """A path strictly inside `release`; anything absolute, drive-qualified or climbing is refused."""
        candidate = confine_or_raise(
            release,
            requested,
            lambda _exc: APIError(
                "destination_not_permitted", "Destination must be a relative path inside output/release", 400
            ),
        )
        if candidate == release.resolve():
            raise APIError("destination_not_permitted", "Destination must name a file", 400)
        return candidate

    def publish_artifact(self, request: Request, document_id: str) -> Response:
        data = self._body(request, dto.PublishRequest)
        root, deps = self._open(request, document_id, data.workspace_id)
        ws = Path(root).resolve()
        doc_root = deps.workspace.doc_root(document_id).resolve()
        configured = (self._resolve(deps, document_id).config or {}).get("output", {})
        fmt = output_format(data.format or (configured.get("format") if isinstance(configured, dict) else None))
        destination = self._destination(doc_root / "output" / "release", data.destination)
        source = doc_root / "output" / "current" / f"{document_id}.{fmt}"
        if not source.is_file():
            raise APIError("publish_source_unavailable", f"The document has no built {fmt} artifact; build it first", 409)
        policy = PipelineMode(data.policy)
        service = deps.package_publications
        try:
            prepared = service.preflight_publish(source, destination, policy=policy)
        except PublishPolicyDeniedError as exc:
            raise APIError("publish_policy_denied", self._clean(str(exc), ws), 422) from exc
        except PackagePublicationError as exc:
            raise APIError("publish_rejected", self._clean(str(exc), ws), 409) from exc
        try:
            resolved, config, renderer = _resolve_publish_inputs(deps, doc_root, fmt)
            current = _current_input_identities(
                resolved=resolved, config=config, renderer=renderer, root=doc_root, output_format=fmt,
            )
        except (DocumentNotFoundError, ValueError, KeyError, OSError, RuntimeError) as exc:  # inputs cannot be proven current
            raise APIError(
                "publish_inputs_unresolvable", self._clean(f"publish requires resolvable current inputs: {exc}", ws), 409,
            ) from exc
        try:
            result = service.publish(prepared, current_identities=current)
        except PackagePublicationError as exc:
            raise APIError("publish_failed", self._clean(str(exc), ws), 409) from exc
        artifact_sha, manifest_sha = sha256_bytes(prepared.source_bytes), sha256_bytes(prepared.manifest_bytes)
        destination_rel = self._rel(ws, result.artifact)
        record_id = "pub-" + sha256_bytes(f"{document_id}\0{destination_rel}\0{artifact_sha}\0{manifest_sha}".encode())[:16]
        self._record(
            request, data.workspace_id, record_id, document_id, destination_rel, artifact_sha, prepared,
            policy=policy.value, warnings=list(result.warnings),
        )
        return Response.json(dto.PublicationResponse(
            id=record_id, document_id=document_id, format=fmt, policy=policy.value,
            source=self._rel(ws, source), destination=destination_rel, manifest=self._rel(ws, result.manifest),
            artifact_sha256=artifact_sha, manifest_sha256=manifest_sha,
            provenance_run=prepared.manifest.provenance_run or "", attestation_sha256=prepared.attestation_sha256,
            identities=_jsonable(current), warnings=list(result.warnings),
        ).model_dump(), 201)

    def _record(
        self, request: Request, body_workspace: str | None, record_id: str, document_id: str,
        destination: str, artifact_sha: str, prepared: Any, *, policy: str, warnings: list[str],
    ) -> None:
        """Project the publication once; a repeat of identical evidence never rewrites the record."""
        store = self._publications()
        if store is None:
            return
        principal = request.principal
        record: dict[str, Any] = {
            "id": record_id, "run_id": prepared.manifest.provenance_run or "", "document_id": document_id,
            "workspace_id": str(request.query.get("workspace_id") or body_workspace or ""),
            "environment": "local", "artifact": document_id, "destination": destination,
            "artifact_sha256": artifact_sha, "published_at": datetime.now(UTC).isoformat(),
            "approver": principal.subject if principal is not None else "local", "status": "passed",
            "policy": policy, "warnings": warnings,
        }
        if principal is not None and principal.tenant_id and principal.organization_id:
            record.update(tenant_id=principal.tenant_id, organization_id=principal.organization_id)
        store.put_if_absent(record)  # atomic: a racing identical publish keeps the first record
