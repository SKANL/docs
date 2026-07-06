# src/docs/domain/context_index_files.py
"""Shared skip-rule for a document's `context/` directory.

Both generated index files (the pre-existing Topic/Q&A `index.md` and the
newer progressive-disclosure `curated-index.md`) and any `_`-prefixed file
are structural/internal artifacts, never agent-authored content. The
context-curation writer (`application/context_files.py`) and every
context-directory reader (`application/collection.py`'s source-collection
globs, `infrastructure/persistence/filesystem_source_repository.py`'s
`read_context_texts`) MUST agree on this rule from one place -- otherwise a
new generated index can silently leak into the evidence/fact-detection
pipeline as if it were confirmed source content (fresh-context review
CRITICAL, PR8 remediation: `curated-index.md` was reachable via
`collect_sources` and the contradiction/sensitive-field text scan before
this module existed).
"""
from __future__ import annotations

# Pre-existing Topic/Q&A context-schema subsystem's index
# (`JsonContextRepository.regenerate_index`) -- unrelated purpose/format,
# same skip rule.
TOPIC_QA_INDEX_FILENAME = "index.md"

# Context-curation's own single progressive-disclosure index
# (`application/context_files.py:build_context_index`), namespaced to avoid
# clobbering `TOPIC_QA_INDEX_FILENAME`.
CURATED_INDEX_FILENAME = "curated-index.md"

_NON_CONTENT_FILENAMES = frozenset({TOPIC_QA_INDEX_FILENAME, CURATED_INDEX_FILENAME})


def is_context_content_filename(filename: str) -> bool:
    """True if `filename` (e.g. "keywords.md") is agent-authored/approved
    context content, not a generated index or an internal (`_`-prefixed)
    file that must never be collected as a source or scanned for facts."""
    if filename.startswith("_"):
        return False
    return filename not in _NON_CONTENT_FILENAMES
