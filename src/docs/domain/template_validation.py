# src/docs/domain/template_validation.py
from __future__ import annotations

import difflib
from typing import Any

from pydantic import BaseModel, ValidationError

from docs.domain.config_vocabulary import known_keys_at
from docs.domain.models.template import (
    Apa7Config,
    ContextSchema,
    Field,
    LengthSpec,
    Section,
    SectionContract,
    StrictPolicy,
    StrictPolicyBlock,
    Template,
    Topic,
)
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


# Top-level blocks every real template ships that no model declares: the
# config envelope `resolve_context` merges and consumes raw. Never near-miss candidates.
_CONFIG_ENVELOPE_BLOCKS = frozenset(
    {
        "advisor_overrides",
        "cross_consistency",
        "documents_tools",
        "format",
        "ledger_seed",
        "normative",
        "output",
        "paths",
        "preliminaries",
        "privacy",
    }
)

# How close an unknown key must be to a real field before it is called a
# typo. 0.8 accepts `required_contents`/`required_content` and
# `ordre`/`order` while leaving `custom_legacy_key` alone.
# ponytail: one difflib ratio, no edit-distance table. Tighten only if a
# real passthrough key ever gets flagged.
_NEAR_MISS_CUTOFF = 0.8


def _near_miss_keys(raw: Any, model: type[BaseModel], path: str) -> list[Issue]:
    """Walk one dict against its model, reporting keys that look like typos.

    A permissive model accepts anything, which is what makes `$comment`
    siblings and untyped contract passthrough work -- and also what let
    `required_contents` be silently dropped. This separates the two by
    resemblance: an unknown key close to a real field is a typo worth a
    warning; one that resembles nothing is a deliberate extension.
    """
    if not isinstance(raw, dict):
        return []
    known = set(model.model_fields) | {
        info.alias for info in model.model_fields.values() if info.alias
    }
    issues: list[Issue] = []
    for key in raw:
        if not isinstance(key, str) or key in known:
            continue
        # `$comment` / `_note`: the documented "this is deliberately not a
        # field" convention. Never a typo by construction.
        if key.startswith(("$", "_")):
            continue
        if path == "" and key in _CONFIG_ENVELOPE_BLOCKS:
            continue
        close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=_NEAR_MISS_CUTOFF)
        if not close:
            continue
        where = f"{path}.{key}" if path else key
        issues.append(
            Issue(
                "warning",
                f"Clave desconocida `{where}`, muy parecida a `{close[0]}`. "
                f"Si es un error de tipeo, la regla que escribiste no se está "
                f"aplicando: el arnés acepta claves extra y las ignora.",
                code="template.unknown_key",
            )
        )
    return issues


def _near_miss_against(known: set[str], raw: Any, path: str) -> list[Issue]:
    """`_near_miss_keys`, but against an explicit key set instead of a model.

    The config envelope has no model to read `model_fields` off -- that is
    the whole reason a typo there was invisible -- so its known keys come
    from `config_vocabulary`. Everything else about the judgement is
    identical, deliberately: same cutoff, same `$`/`_` exemption, same code.
    Two mechanisms for one concept would be two things to keep in step.
    """
    if not isinstance(raw, dict) or not known:
        return []
    issues: list[Issue] = []
    for key in raw:
        if not isinstance(key, str) or key in known or key.startswith(("$", "_")):
            continue
        close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=_NEAR_MISS_CUTOFF)
        if not close:
            continue
        where = f"{path}.{key}" if path else key
        issues.append(
            Issue(
                "warning",
                f"Clave de configuración desconocida `{where}`, muy parecida a "
                f"`{close[0]}`. El arnés no lee esta clave, así que el valor que "
                f"declaraste no se está aplicando. Si es un error de tipeo, "
                f"corregilo; si la clave quedó de una versión anterior, "
                f"prefijala con `_` para conservarla como nota.",
                code="template.unknown_key",
            )
        )
    return issues


def _check_config_envelope(raw: dict[str, Any], path: tuple[str, ...] = ()) -> list[Issue]:
    """Walk the unmodelled config blocks, reporting keys that look like typos.

    Descends only where the vocabulary knows the level, so a block this
    harness version does not read is passed over rather than second-guessed:
    the envelope is open by contract (`resolve_context` merges three sources via `_deep_merge`),
    and a forward-declared block is not a mistake.
    """
    known = known_keys_at(path)
    if not known:
        return []
    issues = _near_miss_against(known, raw, ".".join(path))
    for key, value in raw.items():
        if isinstance(key, str) and key in known and isinstance(value, dict):
            issues.extend(_check_config_envelope(value, (*path, key)))
    return issues


def _check_near_miss_keys(raw: dict[str, Any]) -> list[Issue]:
    """Apply the near-miss walk across every level a template nests."""
    issues = _near_miss_keys(raw, Template, "")
    for index, section in enumerate(raw.get("sections") or []):
        issues.extend(_near_miss_keys(section, Section, f"sections[{index}]"))
    for section_id, contract in (raw.get("section_contracts") or {}).items():
        issues.extend(_near_miss_keys(contract, SectionContract, f"section_contracts.{section_id}"))
        if isinstance(contract, dict):
            issues.extend(
                _near_miss_keys(contract.get("length"), LengthSpec, f"section_contracts.{section_id}.length")
            )
    context_schema = raw.get("context_schema")
    issues.extend(_near_miss_keys(context_schema, ContextSchema, "context_schema"))
    if isinstance(context_schema, dict):
        for index, topic in enumerate(context_schema.get("topics") or []):
            issues.extend(_near_miss_keys(topic, Topic, f"context_schema.topics[{index}]"))
            if isinstance(topic, dict):
                for f_index, field in enumerate(topic.get("fields") or []):
                    issues.extend(
                        _near_miss_keys(field, Field, f"context_schema.topics[{index}].fields[{f_index}]")
                    )
    issues.extend(_near_miss_keys(raw.get("apa7"), Apa7Config, "apa7"))
    strict_policy = raw.get("strict_policy")
    issues.extend(_near_miss_keys(strict_policy, StrictPolicy, "strict_policy"))
    if isinstance(strict_policy, dict):
        for block in ("draft", "strict"):
            issues.extend(
                _near_miss_keys(strict_policy.get(block), StrictPolicyBlock, f"strict_policy.{block}")
            )
    return issues


def validate_template(raw: dict[str, Any]) -> list[Issue]:
    """Structural + completeness validation over the RAW template dict
    (design.md Decision 1b, spec: document-template "Template Structural
    and Completeness Validation"). Separate from `Template(extra="allow")`
    itself -- open extension stays a contract, this only enforces what a
    template declares is internally consistent and complete. Does NOT
    reject unknown keys, but DOES point out the ones that look like typos
    (`_check_near_miss_keys`)."""
    issues = _check_required_blocks(raw)
    issues.extend(_check_incomplete_sentinels(raw))
    issues.extend(_check_near_miss_keys(raw))
    issues.extend(_check_config_envelope(raw))

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
