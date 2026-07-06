# tests/unit/application/test_context_index.py
from docs.application.context_files import build_context_files, build_context_index


def test_index_has_three_level_progressive_disclosure_structure():
    index = build_context_index(build_context_files({}))

    assert "## Overview" in index
    assert "## Files" in index
    assert "## References" in index
    # Overview must come before Files, which must come before References.
    assert index.index("## Overview") < index.index("## Files") < index.index("## References")


def test_index_lists_one_summary_entry_per_generated_context_file_with_a_link():
    context_files = build_context_files({})

    index = build_context_index(context_files)

    for concern in context_files:
        assert f"({concern}.md)" in index


def test_index_skips_index_and_underscore_prefixed_entries_like_read_context_texts():
    context_files = {
        "tone": "content",
        "index": "should never be listed",
        "_requests": "should never be listed",
        "_detection": "should never be listed",
    }

    index = build_context_index(context_files)

    assert "(tone.md)" in index
    assert "(index.md)" not in index
    assert "(_requests.md)" not in index
    assert "(_detection.md)" not in index


def test_build_context_files_never_produces_an_index_entry_itself():
    # Exactly one index file must exist; the per-concern builder must never
    # emit an "index" key alongside the concern files themselves.
    assert "index" not in build_context_files({})


def test_index_generation_is_deterministic_across_runs():
    context_files = build_context_files({"a": "# Uno\nTexto."})

    first = build_context_index(context_files)
    second = build_context_index(context_files)

    assert first == second
