from __future__ import annotations

from typing import Protocol


class MarkdownNormalizerPort(Protocol):
    """Port for deterministic Markdown normalization."""

    def normalize(self, source: str) -> str: ...
