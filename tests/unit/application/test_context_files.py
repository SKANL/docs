# tests/unit/application/test_context_files.py
import subprocess

import pytest

from docs.application.context_files import (
    CONCERNS,
    build_context_file_skeleton,
    build_context_files,
    merge_context_file,
)


def _fill_marker(concern: str) -> tuple[str, str]:
    return (
        f"<!-- AGENT-FILL:{concern}-content START -->",
        f"<!-- AGENT-FILL:{concern}-content END -->",
    )


def test_all_five_concerns_are_covered():
    assert set(CONCERNS) == {
        "formatting-rules",
        "keywords",
        "structure",
        "tone",
        "writing-style",
    }


def test_skeleton_has_heading_instructions_and_empty_agent_fill_block():
    for concern in CONCERNS:
        skeleton = build_context_file_skeleton(concern, {})
        assert "## Instructions" in skeleton
        start, end = _fill_marker(concern)
        assert start in skeleton
        assert end in skeleton
        between = skeleton.split(start, 1)[1].split(end, 1)[0]
        assert between.strip() == "", f"{concern} AGENT-FILL block must start empty"


def test_unknown_concern_raises_value_error():
    with pytest.raises(ValueError):
        build_context_file_skeleton("bogus-concern", {})


def test_keywords_concern_extracts_keyword_tokens_from_ingested_sources():
    ingested = {"source-a": "Resultados del Proyecto y Alcance"}
    skeleton = build_context_file_skeleton("keywords", ingested)
    assert "alcance" in skeleton
    assert "resultados" in skeleton
    assert "proyecto" in skeleton


def test_non_keyword_concern_extracts_headings_from_ingested_sources():
    ingested = {"source-a": "# Introduccion\nTexto.\n## Alcance\n"}
    skeleton = build_context_file_skeleton("tone", ingested)
    assert "Introduccion" in skeleton
    assert "Alcance" in skeleton


def test_build_context_files_returns_exactly_the_five_concerns():
    result = build_context_files({})
    assert set(result) == set(CONCERNS)


def test_merge_preserves_agent_authored_content_when_present():
    concern = "tone"
    start, end = _fill_marker(concern)
    existing = (
        f"# Tone\n\n{start}\nKeep a formal, academic tone.\n{end}\n"
    )
    fresh_skeleton = build_context_file_skeleton(concern, {})

    merged = merge_context_file(concern, fresh_skeleton, existing)

    assert "Keep a formal, academic tone." in merged


def test_merge_keeps_fresh_skeleton_when_existing_has_no_agent_content():
    concern = "tone"
    fresh_skeleton = build_context_file_skeleton(concern, {})

    merged = merge_context_file(concern, fresh_skeleton, existing_text=None)

    assert merged == fresh_skeleton


def test_regeneration_across_full_file_set_preserves_agent_edits():
    ingested = {"source": "# Tone\nFormal register throughout.\n"}
    first_pass = build_context_files(ingested)
    start, end = _fill_marker("tone")
    agent_edited = first_pass["tone"].replace(
        f"{start}\n{end}\n",
        f"{start}\nKeep a formal, academic tone.\n{end}\n",
    )

    second_pass = build_context_files(ingested, existing_files={"tone": agent_edited})

    assert "Keep a formal, academic tone." in second_pass["tone"]
    # Sibling concerns untouched by the edit still regenerate their own fresh skeleton.
    assert second_pass["keywords"] == build_context_files(ingested)["keywords"]


def test_same_inputs_same_output():
    ingested = {"a": "# Uno\nTexto.\n", "b": "# Dos\nMas texto."}

    first = build_context_files(ingested)
    second = build_context_files(ingested)

    assert first == second


def test_no_agent_process_invoked_on_completion(monkeypatch):
    def _forbidden_run(*args, **kwargs):
        raise AssertionError("context-curation must not invoke external/agent processes")

    monkeypatch.setattr(subprocess, "run", _forbidden_run)

    result = build_context_files({"a": "# Uno\nTexto."})

    assert set(result) == set(CONCERNS)
