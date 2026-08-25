# src/docs/domain/config_vocabulary.py
"""Every configuration key the harness reads, in one place.

A template is hand-written JSON and its ten config blocks -- `format`,
`paths`, `normative`, `privacy`, `output`, `preliminaries`,
`cross_consistency`, `advisor_overrides`, `documents_tools`, `ledger_seed` --
are declared by no model at all: `resolve_context` merges them via `_deep_merge` and hands every
service a `dict[str, Any]`. So a mistyped key is accepted, ignored, and
changes the document. `format.page_margins_cm.non_cover.to` instead of `top`
leaves the top margin at Word's 2.54cm default while the template validates
and the build succeeds.

This is the field list `template_validation` needs to say "you meant `top`",
in the same way it reads `model_fields` for the modelled half.

It is NOT hand-maintained on trust: `tests/architecture/test_config_vocabulary.py`
AST-scans every `config[...]` access under `src/docs` and fails if this
declaration and the code disagree. Keys the scan cannot see -- read through a
loop variable or reached via a different local name -- are listed in
`DYNAMICALLY_READ_KEYS` with the site that reads them, and each one is pinned
by a behavioural test rather than an assertion about source text.

Pure data. No I/O, no imports from other layers.
"""
from __future__ import annotations

from typing import Any

# Keys the AST scan finds directly. Generated from the source, not recalled.
SCANNED_CONFIG_KEYS: dict[str, Any] = {
    "advisor_overrides": {},
    "apa7": {
        "citation_style": {},
    },
    "collect_facts_seed": {},
    "cross_consistency": {
        "contested_stack_terms": {},
        "duration_consistency": {},
    },
    "doc_id": {},
    "documents_dir": {},
    "documents_tools": {
        "enabled": {},
        "required_in_strict": {},
        "scripts": {},
    },
    "evidence_sources": {},
    "format": {
        "keyword_bold_terms": {},
        "page_margins_cm": {
            "non_cover": {},
        },
        "page_size": {},
    },
    "ledger_seed": {},
    "normative": {
        "normative_source": {},
    },
    "output": {
        "body_name": {},
        "draft_name": {},
        "format": {},
        "html_name": {},
    },
    "paths": {
        "assets_dir": {},
        "code_evidence_manifest": {},
        "context_dir": {},
        "corrections_applied": {},
        "corrections_inbox_dir": {},
        "documents_scripts_dir": {},
        "example_pdf": {},
        "extracted_dir": {},
        "extracted_dir_policy": {},
        "fact_ledger": {},
        "inbox_dir": {},
        "issues_manifest": {},
        "manual_dir": {},
        "manual_pdf": {},
        "output_draft_dir": {},
        "output_qa_dir": {},
        "prompts_dir": {},
        "rules_manifest": {},
        "runs_dir": {},
        "sections_dir": {},
        "source_manifest": {},
        "template_docx": {},
    },
    "preliminaries": {},
    "privacy": {
        "forbidden_in_body_patterns": {},
        "sensitive_context_fields": {},
    },
    "project": {
        "scope_policy": {},
    },
    "section_contracts": {},
    "sections": {},
    "strict_policy": {},
    "structure": {},
    "templates_dir": {},
    "title": {},
}

# Keys no AST scan can attribute to `config`, with the site that reads them.
# Each is pinned by a behavioural test, which is stronger evidence than a
# pattern match over source text would be.
DYNAMICALLY_READ_KEYS: dict[str, tuple[str, ...]] = {
    # `apply_non_cover_section_layout` iterates a literal (attr, key) list,
    # so the key is a loop variable by the time `.get()` sees it. This is
    # exactly the level the mistyped-margin bug lives at.
    "format.page_margins_cm.non_cover": ("top", "right", "bottom", "left"),
    # `_check_margins_and_cover_policy` reads these off `template.model_extra`
    # rather than off a name called `config`.
    "format.page_margins_cm": ("cover_policy",),
}


def known_keys_at(path: tuple[str, ...]) -> set[str]:
    """The config keys valid directly under `path` (empty tuple = top level)."""
    node: Any = SCANNED_CONFIG_KEYS
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
    keys = set(node) if isinstance(node, dict) else set()
    return keys | set(DYNAMICALLY_READ_KEYS.get(".".join(path), ()))
