from __future__ import annotations

from typing import Protocol


class TranslationMemoryPort(Protocol):
    """Content-addressed store of already-made translations.

    This is what supplies determinism: the engine may be non-deterministic,
    but a cache hit reproduces the exact previous bytes. Keys come from
    `domain.translation_memory_key.memory_key`.
    """

    def get(self, key: str) -> str | None:
        """The stored translation for `key`, or `None` on a miss."""
        ...

    def put(self, key: str, source_text: str, translation: str) -> None:
        """Store `translation` under `key`. `source_text` is kept for audit."""
        ...
