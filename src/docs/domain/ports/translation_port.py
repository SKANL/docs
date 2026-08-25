from __future__ import annotations

from typing import Protocol


class TranslationPort(Protocol):
    """One text block in, one translated block out.

    Implementations are never asked to decide WHETHER to translate. A refusal,
    an empty answer or a raised exception is handled by
    `domain.translation_guard.guarded_translate`, which degrades a single
    block and lets the run continue.
    """

    engine_id: str
    """Stable identifier for this engine, mixed into the translation-memory
    key so switching engines produces new translations rather than silently
    reusing ones made under different rules."""

    accepts_unchanged: bool
    """Whether a response identical to its input counts as a translation.

    `False` for a live engine: echoing the input is a failure mode there.
    `True` for an engine reading an explicitly filled slot, where "1",
    "ACME" and a code snippet are legitimately identical in every language
    and must not be reported as untranslated forever."""

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate `text` into `target_lang`. May raise; the caller guards."""
        ...
