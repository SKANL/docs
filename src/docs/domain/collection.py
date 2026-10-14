# src/docs/domain/collection.py
from __future__ import annotations

import json
import re as _re
from collections.abc import Collection
from typing import Any

from docs.domain.identity import sha256_bytes

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


def _fact_key(fact: dict[str, Any]) -> str:
    return f"{fact.get('classification')}|{fact.get('claim')}|{fact.get('source')}"


def identify_facts(facts: list[dict[str, Any]], known_paths: Collection[str]) -> list[dict[str, Any]]:
    """Return copies of `facts` with a content-derived `id` and, when the
    fact's source is one of `known_paths`, a structured `source_path`."""
    identified: list[dict[str, Any]] = []
    for fact in facts:
        item = {**fact, "id": sha256_bytes(_fact_key(fact).encode("utf-8"))[:16]}
        if "source_path" not in item and fact.get("source") in known_paths:
            item["source_path"] = fact["source"]
        identified.append(item)
    return identified


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = _fact_key(fact)
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    return deduped


def extract_github_repo(remote_url: str) -> str:
    match = _GITHUB_REMOTE_RE.search(remote_url)
    if not match:
        return ""
    return match.group("repo").removesuffix(".git")
