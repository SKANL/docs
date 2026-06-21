# src/docs/domain/collection.py
from __future__ import annotations

import json
import re as _re
from typing import Any

_CONFIRMED_SOURCE_TYPES = {"approved_context", "institutional_manual", "mobile_code_or_docs"}

_GITHUB_REMOTE_RE = _re.compile(r"github\.com[:/](?P<repo>[^/]+/[^/.]+(?:-[^/.]*)?)")


def classify_source(source_type: str) -> str:
    if source_type in _CONFIRMED_SOURCE_TYPES:
        return "confirmado"
    if source_type == "example_reference":
        return "fuera_de_alcance"
    if source_type == "cover_template":
        return "confirmado"
    return "pendiente"


def parse_gh_issues(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"No se pudo parsear salida JSON de gh: {exc}") from exc
    issues: list[dict[str, Any]] = []
    for item in data:
        labels = item.get("labels") or []
        issues.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "url": item.get("url", ""),
                "labels": [label.get("name", "") for label in labels if isinstance(label, dict)],
                "classification": "confirmado",
                "source": "github_issues",
            }
        )
    return issues


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = f"{fact.get('classification')}|{fact.get('claim')}|{fact.get('source')}"
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    return deduped


def extract_github_repo(remote_url: str) -> str:
    match = _GITHUB_REMOTE_RE.search(remote_url)
    if not match:
        return ""
    return match.group("repo").removesuffix(".git")
