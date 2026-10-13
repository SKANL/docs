# src/docs/application/output_names.py
from __future__ import annotations

from typing import Any

# Single source of truth for the DOCX draft/body default output-name
# FORMATS. `PipelineService` (application/pipeline.py) and
# `DocxRendererAdapter` (application/docx_assembly.py) both resolve these
# defaults from here instead of each declaring their own copy of the
# literal (tech-debt closeout D1 — pull-forward of PR8 task 8.1's
# `_DRAFT_DOCX_NAME` drop). Defaults derive from the document id rather
# than a fixed literal: a template that declares no explicit
# `config["output"]` name must not silently inherit estadia's "tesina"
# branding (residual estadia-coupling fix). Estadia's own template
# declares its `output` block explicitly, so its behavior stays
# byte-identical.
DEFAULT_DRAFT_DOCX_NAME_FORMAT = "{doc_id}-draft.docx"
DEFAULT_BODY_DOCX_NAME_FORMAT = "{doc_id}-body.docx"

# Same seam for the HTML renderer's single-file output name (PR2, item C-html).
DEFAULT_HTML_NAME_FORMAT = "{doc_id}-draft.html"


def resolve_draft_docx_name(doc_id: str, config: dict[str, Any]) -> str:
    default = DEFAULT_DRAFT_DOCX_NAME_FORMAT.format(doc_id=doc_id)
    return config.get("output", {}).get("draft_name", default)


def resolve_body_docx_name(doc_id: str, config: dict[str, Any]) -> str:
    default = DEFAULT_BODY_DOCX_NAME_FORMAT.format(doc_id=doc_id)
    return config.get("output", {}).get("body_name", default)


def resolve_html_name(doc_id: str, config: dict[str, Any]) -> str:
    default = DEFAULT_HTML_NAME_FORMAT.format(doc_id=doc_id)
    return config.get("output", {}).get("html_name", default)
