# src/docs/domain/translation_memory_key.py
"""The cache key that makes a non-deterministic engine reproducible.

This lives in the DOMAIN, not beside the filesystem adapter, because
`TranslateService` computes the key and application code must never import
infrastructure. The key is pure hashing and has no business knowing where the
entry is stored.

The engine id and glossary version are part of the key on purpose: changing
either SHOULD produce a new translation rather than silently reusing one made
under different rules.

Pure data. No I/O, no imports from other layers.
"""
from __future__ import annotations

import hashlib

# NUL joins the components so no combination can collide by concatenation --
# ("ab", "c") and ("a", "bc") must never share a key.
_SEPARATOR = "\x00"


def memory_key(
    text: str, source_lang: str, target_lang: str, engine_id: str, glossary_version: str
) -> str:
    payload = _SEPARATOR.join([text, source_lang, target_lang, engine_id, glossary_version])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
