"""Strict transport DTOs for source, asset, classification, and context routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthoringDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# Requests. `workspace_id` may also arrive as a query parameter.
class AssetAddRequest(AuthoringDTO):
    workspace_id: str | None = None
    filename: str
    content_base64: str
    name: str = ""


class SourceUpload(AuthoringDTO):
    filename: str
    content_base64: str


class SourceIngestRequest(AuthoringDTO):
    workspace_id: str | None = None
    files: list[SourceUpload] = Field(default_factory=list)


class ContextElicitRequest(AuthoringDTO):
    workspace_id: str | None = None
    topic: str = ""


class WorkspaceScopedRequest(AuthoringDTO):
    workspace_id: str | None = None


class ClassificationConfirmRequest(AuthoringDTO):
    workspace_id: str | None = None
    relative_path: str
    confirmed_role: Literal["evidence", "example", "normative"]


# Responses.
class AssetItem(AuthoringDTO):
    name: str


class AssetResponse(AuthoringDTO):
    document_id: str
    name: str
    path: str


class AssetListResponse(AuthoringDTO):
    document_id: str
    kind: str
    items: list[AssetItem]


class AssetRemoveResponse(AuthoringDTO):
    document_id: str
    removed: str


class UploadedSource(AuthoringDTO):
    filename: str
    sha256: str
    size: int
    deduplicated: bool


class IngestStage(AuthoringDTO):
    name: str
    succeeded: bool
    status: str | None = None
    processed: int | None = None
    errors: list[str]
    warnings: list[str]
    files: list[dict[str, Any]]


class SourceIngestResponse(AuthoringDTO):
    document_id: str
    succeeded: bool
    artifacts: list[str]
    uploaded: list[UploadedSource]
    stages: list[IngestStage]


class ClassificationResponse(AuthoringDTO):
    document_id: str
    items: list[dict[str, Any]]


class ContextRequestsResponse(AuthoringDTO):
    document_id: str
    path: str
    markdown: str


class ContextIngestResponse(AuthoringDTO):
    document_id: str
    topics: list[str]


class ContextTopicResponse(AuthoringDTO):
    document_id: str
    topic: str
    content: str


class ContextRemoveResponse(AuthoringDTO):
    document_id: str
    removed: str


# Section authoring (S2.2). Paths are relative to the document root.
class SectionBuildResponse(AuthoringDTO):
    document_id: str
    section_id: str
    path: str
    proposal: bool  # True when authored content exists and a candidate was written instead


class ContextPackRequest(AuthoringDTO):
    workspace_id: str | None = None
    target: str  # a section id, "all" or "document"


class ContextPackResponse(AuthoringDTO):
    document_id: str
    target: str
    paths: list[str]


class ReviewRequest(AuthoringDTO):
    workspace_id: str | None = None
    strict: bool = False


class DocumentReviewRequest(ReviewRequest):
    dimensions: list[Literal[
        "editorial", "evidence", "consistency", "structural", "accessibility", "visual", "reproducibility",
    ]] = Field(default_factory=list)


class ReviewFinding(AuthoringDTO):
    severity: str
    message: str
    code: str
    dimension: str
    evidence: str | None = None
    resolution_condition: str | None = None
    section: str | None = None
    file: str | None = None
    page: int | None = None
    stage_originator: str | None = None


class ReviewResponse(AuthoringDTO):
    document_id: str
    section_id: str | None
    passed: bool
    findings: list[ReviewFinding]


class StampRequest(AuthoringDTO):
    workspace_id: str | None = None
    by: str = Field(min_length=1)
    model: str = ""


class StampResponse(AuthoringDTO):
    document_id: str
    section_id: str
    path: str
    authored_by: str
    model: str
    stamped_at: str


class RevisionRequest(AuthoringDTO):
    workspace_id: str | None = None
    target_id: str
    new_body: str | None = None
    new_value: str | None = None
    request: str = "API revision"
    field: str = ""
    strict: bool = False


class RevisionResponse(AuthoringDTO):
    target_id: str
    diff: str
    summary: str
    changed_sections: list[str]
    diff_path: str


class PipelinePlanRequest(AuthoringDTO):
    workspace_id: str | None = None
    pipeline_id: str = "document"
    format: str = "docx"


class PipelinePlanResponse(AuthoringDTO):
    document_id: str
    pipeline_id: str
    stages: list[str]
    external_artifacts: list[str]
    contracts: list[dict[str, Any]]


class PipelineRunRequest(AuthoringDTO):
    workspace_id: str | None = None
    pipeline_id: str = "document"
    format: str | None = None
    policy: Literal["draft", "strict", "release"] | None = None
    strict: bool = False
    release: bool = False


class RunLinks(AuthoringDTO):
    self: str
    progress: str
    cancel: str


class PipelineRunResponse(AuthoringDTO):
    id: str
    status: str
    document_id: str
    pipeline_id: str
    format: str
    policy: str
    links: RunLinks


# Quality operations (evidence, baseline, inspect, diff, qa-docx, corrections).
class BaselinePromotionRequest(AuthoringDTO):
    workspace_id: str | None = None
    run_id: str
    name: str | None = None
    update: bool = False


class BaselinePage(AuthoringDTO):
    name: str
    sha256: str


class BaselinePromotionResponse(AuthoringDTO):
    run_id: str
    name: str
    destination: str
    replaced: bool
    pages: list[BaselinePage]


class EvidenceArtifactRef(AuthoringDTO):
    id: str
    kind: str
    digest: str
    media_type: str


class PreviewAvailability(AuthoringDTO):
    available: bool
    artifact_ids: list[str]


class EvidenceBundleResponse(AuthoringDTO):
    run_id: str
    evidence_sha256: str
    passport: dict[str, Any]
    artifacts: list[EvidenceArtifactRef]
    findings: list[dict[str, Any]]
    previews: PreviewAvailability


class ArtifactReport(AuthoringDTO):
    path: str
    media_type: str
    sha256: str
    size_bytes: int


class ArtifactInspectResponse(ArtifactReport):
    artifact_id: str


class ArtifactDiffRequest(AuthoringDTO):
    workspace_id: str | None = None
    left: str
    right: str


class ArtifactDiffResponse(AuthoringDTO):
    same: bool
    left: ArtifactReport
    right: ArtifactReport
    text_diff: list[str]


class QaDocxRequest(AuthoringDTO):
    workspace_id: str | None = None
    artifact_id: str | None = None
    strict: bool = False


class QaDocxResponse(AuthoringDTO):
    document_id: str
    docx: str
    strict: bool
    passed: bool
    message: str | None
    degraded: bool
    degraded_reason: str | None
    report: str | None


class CorrectionsResponse(AuthoringDTO):
    document_id: str
    applied: int


class PackageRequest(AuthoringDTO):
    workspace_id: str | None = None
    run_id: str | None = None  # optional reference: the run this package is cut from
    name: str | None = None  # archive stem under artifacts/packages; defaults to the run id or "current"


class PackageResponse(AuthoringDTO):
    document_id: str
    run_id: str | None
    source: str
    destination: str
    sha256: str
    size_bytes: int


class PublishRequest(AuthoringDTO):
    workspace_id: str | None = None
    format: str | None = None
    destination: str  # relative to the document's output/release directory
    policy: Literal["draft", "strict", "release"] = "release"


class PublicationResponse(AuthoringDTO):
    id: str
    document_id: str
    format: str
    policy: str
    source: str
    destination: str
    manifest: str
    artifact_sha256: str
    manifest_sha256: str
    provenance_run: str
    attestation_sha256: str
    identities: dict[str, Any]
    warnings: list[str]


# -- templates, document summary, document import (S6.1) ------------------------
class TemplateCreateRequest(AuthoringDTO):
    workspace_id: str | None = None
    name: str


class TemplateUseRequest(AuthoringDTO):
    workspace_id: str | None = None
    force: bool = False


class TemplateValidateRequest(AuthoringDTO):
    workspace_id: str | None = None
    template: dict[str, Any] | None = None  # a draft to check instead of the stored file; never written


class TemplateShowResponse(AuthoringDTO):
    name: str
    template: dict[str, Any]


class TemplateWriteResponse(AuthoringDTO):
    name: str
    path: str  # workspace-relative


class TemplateValidationResponse(AuthoringDTO):
    name: str
    passed: bool
    issues: list[dict[str, Any]]


class DocumentSummaryResponse(AuthoringDTO):
    document_id: str
    summary: dict[str, Any]  # exactly what `doc status --json` prints


class DocumentImportRequest(AuthoringDTO):
    workspace_id: str | None = None
    filename: str
    content_base64: str


class DocumentImportResponse(AuthoringDTO):
    document_id: str
    filename: str
    path: str  # workspace-relative
    sha256: str
    size: int
    mime_type: str
    deduplicated: bool
