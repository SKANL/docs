# tests/unit/domain/test_context_index_files.py
"""RED-first coverage for the shared context-directory skip-filter.

Centralizes the "index files and `_`-prefixed files are never content"
rule in one domain-level place, consumed by both the context-curation
writer (`application/context_files.py`) and every context-directory
reader (`application/collection.py`'s glob loops,
`infrastructure/persistence/filesystem_source_repository.py:read_context_texts`).
"""
from docs.domain.context_index_files import (
    CURATED_INDEX_FILENAME,
    TOPIC_QA_INDEX_FILENAME,
    is_context_content_filename,
)


def test_topic_qa_index_file_is_not_content():
    assert is_context_content_filename(TOPIC_QA_INDEX_FILENAME) is False


def test_curated_index_file_is_not_content():
    assert is_context_content_filename(CURATED_INDEX_FILENAME) is False


def test_underscore_prefixed_file_is_not_content():
    assert is_context_content_filename("_requests.md") is False


def test_ordinary_concern_file_is_content():
    assert is_context_content_filename("keywords.md") is True
    assert is_context_content_filename("scope.md") is True


def test_filename_constants_are_the_expected_literal_values():
    # Locks the literal values so a typo in either constant can't silently
    # desync the writer (`context_files.py`) from the readers.
    assert TOPIC_QA_INDEX_FILENAME == "index.md"
    assert CURATED_INDEX_FILENAME == "curated-index.md"
