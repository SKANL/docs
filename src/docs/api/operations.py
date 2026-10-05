"""Declarative registry for HTTP operations that mirror a CLI command.

One entry drives the dynamic route match, its RBAC scope, its OpenAPI path and
its capability-catalogue row, so a new route cannot be added to one of those
and forgotten in another.  Older routes keep their hand-written tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import authoring_dto as dto


@dataclass(frozen=True)
class Operation:
    cli_commands: tuple[str, ...]
    method: str
    path: str
    scope: str
    summary: str
    handler: str  # method name on the route object named by `routes`
    request: type[dto.AuthoringDTO] | None
    response: type[dto.AuthoringDTO]
    success_status: int = 200
    routes: str = "authoring"  # key of the handler object ("authoring", "sections", "pipeline" or "quality")

    def request_ref(self) -> dict[str, str] | None:
        return _ref(self.request) if self.request else None

    def response_ref(self) -> dict[str, str]:
        return _ref(self.response)


def _ref(model: type[dto.AuthoringDTO]) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{model.__name__}"}


_DOC = "/v2/documents/{document_id}"

OPERATIONS: tuple[Operation, ...] = (
    Operation(("asset list",), "GET", f"{_DOC}/assets", "documents:read", "List document assets",
              "list_assets", None, dto.AssetListResponse),
    Operation(("asset add",), "POST", f"{_DOC}/assets", "documents:write", "Add document asset",
              "add_asset", dto.AssetAddRequest, dto.AssetResponse, 201),
    Operation(("asset rm",), "DELETE", f"{_DOC}/assets/{{asset_name}}", "documents:write",
              "Remove document asset", "remove_asset", None, dto.AssetRemoveResponse),
    Operation(("source ingest", "document ingest"), "POST", f"{_DOC}/ingest", "documents:write",
              "Ingest document sources", "ingest_sources", dto.SourceIngestRequest, dto.SourceIngestResponse),
    Operation(("context elicit",), "POST", f"{_DOC}/context/requests", "documents:write",
              "Write context questionnaire", "elicit_context", dto.ContextElicitRequest,
              dto.ContextRequestsResponse),
    Operation(("context ingest",), "POST", f"{_DOC}/context/ingest", "documents:write",
              "Ingest context answers", "ingest_context", dto.WorkspaceScopedRequest, dto.ContextIngestResponse),
    Operation(("context show",), "GET", f"{_DOC}/context/{{topic_id}}", "documents:read",
              "Show context topic", "show_context_topic", None, dto.ContextTopicResponse),
    Operation(("build-section",), "POST", f"{_DOC}/sections/{{section_id}}/build", "documents:write",
              "Build section scaffold", "build_section", dto.WorkspaceScopedRequest, dto.SectionBuildResponse,
              routes="sections"),
    Operation(("pack-context",), "POST", f"{_DOC}/context-pack", "documents:write",
              "Pack authoring context", "pack_context", dto.ContextPackRequest, dto.ContextPackResponse,
              routes="sections"),
    Operation(("review-section",), "POST", f"{_DOC}/sections/{{section_id}}/review", "documents:write",
              "Review section", "review_section", dto.ReviewRequest, dto.ReviewResponse, routes="sections"),
    Operation(("review-document",), "POST", f"{_DOC}/review", "documents:write",
              "Review document", "review_document", dto.DocumentReviewRequest, dto.ReviewResponse,
              routes="sections"),
    Operation(("stamp-section",), "POST", f"{_DOC}/sections/{{section_id}}/stamp", "documents:write",
              "Stamp section", "stamp_section", dto.StampRequest, dto.StampResponse, routes="sections"),
    Operation(("context rm",), "DELETE", f"{_DOC}/context/{{topic_id}}", "documents:write",
              "Remove context topic", "remove_context_topic", None, dto.ContextRemoveResponse),
    Operation(("document plan",), "POST", f"{_DOC}/plan", "documents:read",
              "Resolve pipeline plan", "plan_document", dto.PipelinePlanRequest, dto.PipelinePlanResponse,
              routes="pipeline"),
    Operation(("document run", "document release"), "POST", f"{_DOC}/run", "documents:write",
              "Enqueue document pipeline run (always asynchronous; follow links.progress; "
              "policy=release equals `document release`)",
              "run_document", dto.PipelineRunRequest, dto.PipelineRunResponse, 202, routes="pipeline"),
    Operation(("document evidence",), "GET", "/v2/runs/{run_id}/evidence", "passport:read",
              "Get run evidence bundle (immutable references; also requires artifacts:read and findings:read)",
              "run_evidence", None, dto.EvidenceBundleResponse, routes="quality"),
    Operation(("document baseline",), "POST", "/v2/baselines/promotions", "baselines:write",
              "Promote a run's rendered previews to a workspace visual baseline",
              "promote_baseline", dto.BaselinePromotionRequest, dto.BaselinePromotionResponse, 201,
              routes="quality"),
    Operation(("document inspect",), "GET", "/v2/artifacts/{artifact_id}/inspect", "artifacts:read",
              "Inspect a workspace artifact", "inspect_artifact", None, dto.ArtifactInspectResponse,
              routes="quality"),
    Operation(("document diff",), "POST", "/v2/artifacts/diff", "artifacts:read",
              "Compare two workspace artifacts", "diff_artifacts", dto.ArtifactDiffRequest,
              dto.ArtifactDiffResponse, routes="quality"),
    Operation(("qa-docx",), "POST", f"{_DOC}/qa-docx", "documents:write",
              "Run rendered DOCX QA (a missing render toolchain is a degraded result)",
              "qa_docx", dto.QaDocxRequest, dto.QaDocxResponse, routes="quality"),
    Operation(("apply-corrections",), "POST", f"{_DOC}/corrections/apply", "documents:write",
              "Apply pending section corrections", "apply_corrections", dto.WorkspaceScopedRequest,
              dto.CorrectionsResponse, routes="quality"),
)

# Shared with the existing classification route, which keeps its own handler
# wiring but reads/writes through the same application function.
CLASSIFICATION_CLI_COMMAND = "document classify"
CLASSIFICATION_ROUTE = "POST /v2/documents/{document_id}/classification"

# `doc revise` keeps its historical route (declared by hand in openapi.py);
# `SectionRoutes.revise` now serves it through the same canonical service.
REVISION_CLI_COMMAND = "doc revise"
REVISION_ROUTE = "POST /v2/documents/{document_id}/revisions"


def match_operation(method: str, path: str) -> tuple[Operation, dict[str, str]] | None:
    """Return the operation and its path parameters for a concrete request."""
    parts = path.strip("/").split("/")
    for operation in OPERATIONS:
        if operation.method != method.upper():
            continue
        template = operation.path.strip("/").split("/")
        if len(template) != len(parts):
            continue
        params: dict[str, str] = {}
        for expected, actual in zip(template, parts, strict=True):
            if expected.startswith("{"):
                if not actual:
                    break
                params[expected[1:-1]] = actual
            elif expected != actual:
                break
        else:
            return operation, params
    return None


def available_cli_routes() -> dict[str, str]:
    routes = {command: f"{op.method} {op.path}" for op in OPERATIONS for command in op.cli_commands}
    routes[CLASSIFICATION_CLI_COMMAND] = CLASSIFICATION_ROUTE
    routes[REVISION_CLI_COMMAND] = REVISION_ROUTE
    return routes


def component_schemas() -> dict[str, dict[str, Any]]:
    """JSON schemas of every DTO the operations (and classification) use."""
    models: set[type[dto.AuthoringDTO]] = {
        model
        for op in OPERATIONS
        for model in (op.request, op.response)
        if model is not None
    }
    models |= {dto.ClassificationConfirmRequest, dto.ClassificationResponse, dto.RevisionRequest, dto.RevisionResponse}
    schemas: dict[str, dict[str, Any]] = {}
    for model in sorted(models, key=lambda m: m.__name__):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    return schemas
