"""Strict transport DTOs for document lifecycle routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DocumentSummaryDTO(DocumentDTO):
    id: str
    title: str
    template: str
    created_at: str
    active: bool


class DocumentPageDTO(DocumentDTO):
    items: list[DocumentSummaryDTO]
    next_cursor: str | None = None


class DocumentCreateRequest(DocumentDTO):
    workspace_id: str
    document_id: str
    template: str = "documento-generico"
    title: str = ""


class DocumentRenameRequest(DocumentDTO):
    new_id: str


class DocumentCurrentResponse(DocumentDTO):
    current_document_id: str | None
    document: DocumentSummaryDTO | None


class DocumentDeleteResponse(DocumentDTO):
    deleted: str
    current_document_id: str | None


def document_openapi_schemas() -> dict[str, dict[str, Any]]:
    page = DocumentPageDTO.model_json_schema(ref_template="#/components/schemas/{model}")
    page.pop("$defs", None)
    page["properties"]["items"]["items"] = {"$ref": "#/components/schemas/document_summary"}
    current = DocumentCurrentResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    current.pop("$defs", None)
    current["properties"]["document"] = {
        "anyOf": [{"$ref": "#/components/schemas/document_summary"}, {"type": "null"}],
        "default": None,
    }
    return {
        "document_summary": DocumentSummaryDTO.model_json_schema(),
        "document_page": page,
        "document_create_request": DocumentCreateRequest.model_json_schema(),
        "document_rename_request": DocumentRenameRequest.model_json_schema(),
        "document_current_response": current,
        "document_delete_response": DocumentDeleteResponse.model_json_schema(),
    }


__all__ = [
    "DocumentCreateRequest",
    "DocumentCurrentResponse",
    "DocumentDeleteResponse",
    "DocumentPageDTO",
    "DocumentRenameRequest",
    "DocumentSummaryDTO",
    "document_openapi_schemas",
]
