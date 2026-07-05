# src/docs/application/output_names.py
from __future__ import annotations

from typing import Any

# Single source of truth for the DOCX draft/body default output names.
# `PipelineService` (application/pipeline.py) and `DocxRendererAdapter`
# (application/docx_assembly.py) both resolve these defaults from here
# instead of each declaring their own copy of the literal (tech-debt
# closeout D1 — pull-forward of PR8 task 8.1's `_DRAFT_DOCX_NAME` drop).
DEFAULT_DRAFT_DOCX_NAME = "tesina-draft.docx"
DEFAULT_BODY_DOCX_NAME = "tesina-body.docx"


def resolve_draft_docx_name(config: dict[str, Any]) -> str:
    return config.get("output", {}).get("draft_name", DEFAULT_DRAFT_DOCX_NAME)


def resolve_body_docx_name(config: dict[str, Any]) -> str:
    return config.get("output", {}).get("body_name", DEFAULT_BODY_DOCX_NAME)
