# src/docs/application/context_files.py
"""Deterministic skeleton + index generation for context-curation (PR7).

Pure functions only — no filesystem I/O, no subprocess/agent invocation.
Callers own reading existing files and writing generated content back to
disk; this module only computes byte-identical Markdown from ingested
source texts. The harness owns all mechanical work (extraction, headings,
skeleton assembly); the agent fills the marked `AGENT-FILL` blocks in a
separate, explicit, auditable step.
"""
from __future__ import annotations

import re

from docs.domain.markdown_text import dedupe_strings, extract_markdown_headings, keyword_set

CONCERNS: tuple[str, ...] = (
    "formatting-rules",
    "keywords",
    "structure",
    "tone",
    "writing-style",
)

_TITLES: dict[str, str] = {
    "formatting-rules": "Formatting Rules",
    "keywords": "Keywords",
    "structure": "Structure",
    "tone": "Tone",
    "writing-style": "Writing Style",
}

_INSTRUCTIONS: dict[str, str] = {
    "formatting-rules": (
        "Describe the formatting conventions the rendered document must "
        "follow (headings, lists, citation style, spacing)."
    ),
    "keywords": "List the key terms and phrases that must appear consistently across the document.",
    "structure": "Describe the expected section order and structural conventions for this document.",
    "tone": "Describe the tone and voice the document must maintain (formal, technical, persuasive, etc.).",
    "writing-style": (
        "Describe stylistic conventions (sentence length, grammatical "
        "person, tense, terminology preferences)."
    ),
}

_FILL_MARKER_TEMPLATE = "AGENT-FILL:{concern}-content"


def _fill_block(concern: str, content: str = "") -> str:
    marker = _FILL_MARKER_TEMPLATE.format(concern=concern)
    return f"<!-- {marker} START -->\n{content}<!-- {marker} END -->\n"


def _agent_fill_pattern(concern: str) -> re.Pattern[str]:
    marker = re.escape(_FILL_MARKER_TEMPLATE.format(concern=concern))
    return re.compile(rf"<!-- {marker} START -->\n(.*?)<!-- {marker} END -->\n", re.DOTALL)


def extracted_terms(concern: str, ingested_texts: dict[str, str]) -> list[str]:
    """Mechanical, deterministic extraction — no cognitive judgement.

    `keywords` reuses the existing `keyword_set` tokenizer; every other
    concern surfaces the deduplicated, sorted Markdown headings found
    across the ingested sources, as raw material for the agent to
    consider when filling the cognitive field.
    """
    if concern == "keywords":
        return sorted(keyword_set(*ingested_texts.values()))
    headings: list[str] = []
    for text in ingested_texts.values():
        headings.extend(extract_markdown_headings(text))
    return sorted(dedupe_strings(headings))


def build_context_file_skeleton(concern: str, ingested_texts: dict[str, str]) -> str:
    """Build a deterministic skeleton for one context-curation concern.

    Raises `ValueError` for unknown concerns instead of silently
    producing a malformed file.
    """
    if concern not in _TITLES:
        raise ValueError(f"Unknown context-curation concern: {concern}")

    title = _TITLES[concern]
    instructions = _INSTRUCTIONS[concern]
    extracted = extracted_terms(concern, ingested_texts)

    lines = [
        f"# {title}",
        "",
        "<!-- HARNESS skeleton -- edit only AGENT-FILL blocks -->",
        "",
        "## Extracted (auto)",
        "",
    ]
    if extracted:
        lines.extend(f"- {item}" for item in extracted)
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "## Instructions",
            "",
            instructions,
            "",
            "## Agent Content",
            "",
        ]
    )
    return "\n".join(lines) + "\n\n" + _fill_block(concern)


def merge_context_file(concern: str, new_skeleton: str, existing_text: str | None) -> str:
    """Idempotent merge: preserve agent-authored `AGENT-FILL` content
    across regeneration. If no existing text is given, or the existing
    file's `AGENT-FILL` block is still empty, the fresh skeleton is
    returned unchanged.
    """
    if not existing_text:
        return new_skeleton

    pattern = _agent_fill_pattern(concern)
    match = pattern.search(existing_text)
    if not match:
        return new_skeleton

    existing_content = match.group(1)
    if not existing_content.strip():
        return new_skeleton

    return pattern.sub(lambda _: _fill_block(concern, existing_content), new_skeleton, count=1)


def build_context_files(
    ingested_texts: dict[str, str],
    existing_files: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the full set of context-curation files, keyed by concern.

    Regeneration is idempotent per concern: an existing file with
    agent-authored `AGENT-FILL` content keeps that content; a concern
    with no prior file (or no agent content yet) gets a fresh skeleton.
    """
    existing_files = existing_files or {}
    return {
        concern: merge_context_file(
            concern,
            build_context_file_skeleton(concern, ingested_texts),
            existing_files.get(concern),
        )
        for concern in CONCERNS
    }


def _is_indexable(stem: str) -> bool:
    """Mirror `FilesystemSourceRepository.read_context_texts`'s skip rule:
    the index file itself and any `_`-prefixed file are never listed."""
    return stem != "index" and not stem.startswith("_")


def build_context_index(context_files: dict[str, str]) -> str:
    """Build the single progressive-disclosure index for a document's
    context files: a level-1 overview, a per-file summary with a link to
    each concern file, and a pointer to on-demand reference detail.
    Reuses `read_context_texts`'s skip rules so `index.md` and any
    `_`-prefixed file never appear as an entry.

    This is the ONLY index this module produces — one Markdown file, no
    JSON companion and no per-concern indexes.
    """
    concerns = sorted(stem for stem in context_files if _is_indexable(stem))

    lines = [
        "# Context Index",
        "",
        "<!-- HARNESS skeleton -- generated file, do not hand-edit -->",
        "",
        "## Overview",
        "",
        (
            "This is the single entry point into this document's context "
            "files. Read a file's one-line summary below before opening "
            "the full file."
        ),
        "",
        "## Files",
        "",
    ]
    for concern in concerns:
        title = _TITLES.get(concern, concern)
        summary = _INSTRUCTIONS.get(concern, "")
        lines.append(f"- [{title}]({concern}.md) -- {summary}")
    lines.extend(
        [
            "",
            "## References",
            "",
            (
                "Full ingested source detail lives under `references/` and "
                "is loaded on demand — it is not summarized above."
            ),
            "",
        ]
    )
    return "\n".join(lines) + "\n"
