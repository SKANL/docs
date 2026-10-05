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
