# src/docs/domain/template_validation.py
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from docs.domain.models.template import Template
from docs.domain.review import Issue
from docs.domain.rules import (
    _check_margins_and_cover_policy,
    _check_missing_section_contracts,
    _check_preliminaries_pagination,
)

_REQUIRED_TOP_LEVEL_BLOCKS = ("type", "title", "sections", "section_contracts", "context_schema")
_SENTINEL_TODO = "TODO"


def _check_required_blocks(raw: dict[str, Any]) -> list[Issue]:
    missing = [block for block in _REQUIRED_TOP_LEVEL_BLOCKS if block not in raw]
    if not missing:
        return []
    return [
        Issue(
            "error",
            f"Faltan bloques requeridos en el template: {', '.join(missing)}.",
            code="template.missing_blocks",
        )
    ]


def _pydantic_errors_to_issues(exc: ValidationError) -> list[Issue]:
    issues = []
    for error in exc.errors():
        path = ".".join(str(part) for part in error["loc"]) or "(raíz)"
        issues.append(
            Issue(
                "error",
                f"Campo inválido `{path}`: {error['msg']}.",
                code="template.invalid_field",
            )
        )
    return issues


def _check_duplicate_topic_ids(template: Template) -> list[Issue]:
    ids = [topic.id for topic in template.context_schema.topics]
    seen: set[str] = set()
    duplicates = sorted({topic_id for topic_id in ids if topic_id in seen or seen.add(topic_id)})  # type: ignore[func-returns-value]
    if not duplicates:
        return []
    return [
        Issue(
            "error",
            f"IDs de tema duplicados en context_schema: {', '.join(duplicates)}.",
            code="template.duplicate_topic_id",
        )
    ]


def _check_incomplete_sentinels(raw: Any, path: str = "") -> list[Issue]:
    """`template init` marks a required-to-fill leaf with `null` or the
    literal string `"TODO"` (design.md Decision 1c) -- both are treated as
    incomplete here. `"$comment"` sibling keys carry human documentation
    only and are never enforced (Decision 1c)."""
    issues: list[Issue] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key == "$comment":
                continue
            issues.extend(_check_incomplete_sentinels(value, f"{path}.{key}" if path else key))
    elif isinstance(raw, list):
        for index, item in enumerate(raw):
            issues.extend(_check_incomplete_sentinels(item, f"{path}[{index}]"))
    elif raw is None or raw == _SENTINEL_TODO:
        issues.append(
            Issue(
                "error",
                f"Campo incompleto (marcador TODO/null sin completar): `{path}`.",
                code="template.incomplete_field",
            )
        )
    return issues


def validate_template(raw: dict[str, Any]) -> list[Issue]:
    """Structural + completeness validation over the RAW template dict
    (design.md Decision 1b, spec: document-template "Template Structural
    and Completeness Validation"). Separate from `Template(extra="allow")`
    itself -- open extension stays a contract, this only enforces what a
    template declares is internally consistent and complete. Does NOT
    reject unknown keys."""
    issues = _check_required_blocks(raw)
    issues.extend(_check_incomplete_sentinels(raw))

    try:
        template = Template.model_validate(raw)
    except ValidationError as exc:
        issues.extend(_pydantic_errors_to_issues(exc))
        return issues

    issues.extend(_check_missing_section_contracts(template))
    issues.extend(_check_duplicate_topic_ids(template))
    issues.extend(_check_preliminaries_pagination(template))
    issues.extend(_check_margins_and_cover_policy(template.model_extra or {}))
    return issues
