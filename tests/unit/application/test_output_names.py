# tests/unit/application/test_output_names.py
"""Output-name resolution: the DEFAULT draft/body/html names must derive
from the document id, never a hardcoded "tesina" literal -- a template
that declares no explicit `config["output"]` name is document-agnostic
by default (residual estadia-coupling fix). An explicit
`config["output"].draft_name/body_name/html_name` always wins."""
from __future__ import annotations

from docs.application.output_names import (
    resolve_body_docx_name,
    resolve_draft_docx_name,
    resolve_html_name,
)


class TestResolveDraftDocxName:
    def test_defaults_to_doc_id_derived_name_when_no_output_config(self):
        assert resolve_draft_docx_name("srs-doc", {}) == "srs-doc-draft.docx"

    def test_uses_configured_draft_name_when_present(self):
        config = {"output": {"draft_name": "custom-draft.docx"}}
        assert resolve_draft_docx_name("srs-doc", config) == "custom-draft.docx"

    def test_default_name_changes_with_doc_id(self):
        assert resolve_draft_docx_name("doc1", {}) == "doc1-draft.docx"
        assert resolve_draft_docx_name("doc2", {}) == "doc2-draft.docx"


class TestResolveBodyDocxName:
    def test_defaults_to_doc_id_derived_name_when_no_output_config(self):
        assert resolve_body_docx_name("srs-doc", {}) == "srs-doc-body.docx"

    def test_uses_configured_body_name_when_present(self):
        config = {"output": {"body_name": "custom-body.docx"}}
        assert resolve_body_docx_name("srs-doc", config) == "custom-body.docx"


class TestResolveHtmlName:
    def test_defaults_to_doc_id_derived_name_when_no_output_config(self):
        assert resolve_html_name("srs-doc", {}) == "srs-doc-draft.html"

    def test_uses_configured_html_name_when_present(self):
        config = {"output": {"html_name": "custom.html"}}
        assert resolve_html_name("srs-doc", config) == "custom.html"
